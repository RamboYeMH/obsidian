#!/usr/bin/env bash
# slog - 通过 supervisor 进程名或 PID 直接查看日志
#
# 不依赖 supervisorctl(需要 sudo)，直接解析 conf.d 配置 + /proc 反查。
#
#   slog                 列出所有进程、PID、日志路径
#   slog game            tail -f game 的 stdout (名称支持模糊匹配)
#   slog 362859          同上，按 PID 反查
#   slog game -e         看 stderr
#   slog game -n 500     最后 500 行，不 follow
#   slog game -g 关键字   过滤(实时)
#   slog game -g 关键字 -A  在所有轮转日志里搜索
#   slog game -p         用 less 分页打开
#   slog --names         只输出进程名，一行一个(供 Tab 补全用)
#
# 环境变量: SLOG_CONF_DIR (默认 /etc/supervisor/conf.d)

set -uo pipefail

CONF_DIR="${SLOG_CONF_DIR:-/etc/supervisor/conf.d}"

if [[ -t 1 ]]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_GREEN=''; C_RED=''; C_YELLOW=''; C_CYAN=''
fi

die() { echo "${C_RED}slog: $*${C_RESET}" >&2; exit 1; }

usage() {
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
    exit 0
}

# ---------------------------------------------------------------------------
# 解析 conf.d/*.conf  ->  每行: name<TAB>command<TAB>stdout<TAB>stderr
# 结果缓存在 CONF_CACHE，awk 全程只跑一次
# ---------------------------------------------------------------------------
CONF_CACHE=''

load_confs() {
    [[ -n $CONF_CACHE ]] && return
    [[ -d $CONF_DIR ]] || die "配置目录不存在: $CONF_DIR (可用 SLOG_CONF_DIR 覆盖)"
    CONF_CACHE=$(awk '
        function flush() {
            if (name != "") printf "%s\t%s\t%s\t%s\n", name, cmd, out, err
            name = ""; cmd = ""; out = ""; err = ""
        }
        function val(line,   v) {
            sub(/^[^=]*=/, "", line)
            sub(/[ \t]+;.*$/, "", line)          # 去掉行内注释
            gsub(/^[ \t]+|[ \t]+$/, "", line)
            return line
        }
        /^[ \t]*\[program:/ {
            flush()
            name = $0
            sub(/^[ \t]*\[program:/, "", name)
            sub(/\].*$/, "", name)
            next
        }
        /^[ \t]*\[/ { flush(); next }             # 其他 section 结束当前 program
        /^[ \t]*command[ \t]*=/       { cmd = val($0); next }
        /^[ \t]*stdout_logfile[ \t]*=/ { out = val($0); next }
        /^[ \t]*stderr_logfile[ \t]*=/ { err = val($0); next }
        END { flush() }
    ' "$CONF_DIR"/*.conf 2>/dev/null)
}

parse_confs() { load_confs; printf '%s\n' "$CONF_CACHE"; }

# ---------------------------------------------------------------------------
# 进程扫描
#   /proc 只遍历一次，结果缓存进关联数组；归一化全用 bash 内建，不 fork 外部命令
# ---------------------------------------------------------------------------
NORM=''            # normalize_str 的输出
FOUND_PID=''       # find_pid 的输出
FOUND_NAME=''      # name_of_pid 的输出
declare -A PROC_BY_CMD
PROC_SCANNED=0

# 归一化命令行：去引号 + 按空白重新分词后用单空格拼接
# conf 里写的是 --loglevel "debug"，/proc 里是 --loglevel debug，归一化后才能比对
normalize_str() {
    local s=${1//\"/}
    s=${s//\'/}
    local -a w
    local IFS=$' \t\n'
    read -ra w <<< "$s"
    NORM="${w[*]}"
}

# 扫描全部 /proc，建立「归一化命令行 -> PID」表
scan_proc() {
    (( PROC_SCANNED )) && return
    PROC_SCANNED=1
    local p key IFS=$' \t\n'
    local -a parts
    for p in /proc/[0-9]*; do
        [[ -r $p/cmdline ]] || continue
        mapfile -d '' -t parts < "$p/cmdline" 2>/dev/null
        (( ${#parts[@]} )) || continue
        key="${parts[*]}"
        [[ -n $key ]] || continue
        [[ -n ${PROC_BY_CMD[$key]:-} ]] || PROC_BY_CMD[$key]=${p##*/}
    done
}

# conf 的 command -> 运行中 PID，结果放 $FOUND_PID
find_pid() {
    scan_proc
    normalize_str "$1"
    FOUND_PID=${PROC_BY_CMD[$NORM]:-}
    [[ -n $FOUND_PID ]]
}

# PID -> program 名，结果放 $FOUND_NAME；返回 2=PID 不存在 1=非 supervisor 进程
name_of_pid() {
    local pid=$1
    [[ -r /proc/$pid/cmdline ]] || return 2
    local -a parts
    local IFS=$' \t\n'
    mapfile -d '' -t parts < "/proc/$pid/cmdline" 2>/dev/null
    local running="${parts[*]}"
    local name cmd rest
    while IFS=$'\t' read -r name cmd rest; do
        [[ -n $cmd ]] || continue
        normalize_str "$cmd"
        if [[ $NORM == "$running" ]]; then
            FOUND_NAME=$name
            return 0
        fi
    done < <(parse_confs)
    return 1
}

# 字节数转可读，纯整数运算(避免 fork bc)，保留 1 位小数并四舍五入
human() {
    local b=${1:-0} u unit
    if   (( b >= 1073741824 )); then u=G; unit=1073741824
    elif (( b >= 1048576 ));    then u=M; unit=1048576
    elif (( b >= 1024 ));       then u=K; unit=1024
    else printf '%dB' "$b"; return; fi
    local v=$(( (b * 20 + unit) / (unit * 2) ))
    printf '%d.%d%s' $(( v / 10 )) $(( v % 10 )) "$u"
}

# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------
list_all() {
    printf "%b%-10s %-8s %-8s %-9s %s%b\n" \
        "$C_BOLD" "NAME" "PID" "STATE" "SIZE" "STDOUT LOG" "$C_RESET"
    local name cmd out err pid state color size
    while IFS=$'\t' read -r name cmd out err; do
        if find_pid "$cmd"; then
            pid=$FOUND_PID; state="RUNNING"; color=$C_GREEN
        else
            pid="-"; state="STOPPED"; color=$C_RED
        fi
        if [[ -f $out ]]; then
            size=$(human "$(stat -c%s "$out")")
        else
            size="-"
        fi
        printf "%b%-10s%b %-8s %b%-8s%b %-9s %b%s%b\n" \
            "$C_CYAN" "$name" "$C_RESET" "$pid" "$color" "$state" "$C_RESET" \
            "$size" "$C_DIM" "${out:-<无>}" "$C_RESET"
    done < <(parse_confs)
    echo
    echo "${C_DIM}用法: slog <进程名|PID> [-e stderr] [-n 行数] [-g 关键字] [-p 分页]${C_RESET}"
}

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
target=""; stream="stdout"; lines=200; pattern=""; pager=0; all_rotated=0; follow=1

while (( $# )); do
    case $1 in
        -h|--help)    usage ;;
        -l|--list)    target="" ; break ;;
        --names)      load_confs; printf '%s\n' "$CONF_CACHE" | cut -f1; exit 0 ;;
        -e|--stderr)  stream="stderr" ;;
        -o|--stdout)  stream="stdout" ;;
        -n|--lines)   lines=${2:?-n 需要行数}; follow=0; shift ;;
        -g|--grep)    pattern=${2:?-g 需要关键字}; shift ;;
        -A|--all)     all_rotated=1; follow=0 ;;
        -p|--pager)   pager=1; follow=0 ;;
        -f|--follow)  follow=1 ;;
        -*)           die "未知选项: $1 (slog -h 看用法)" ;;
        *)            [[ -z $target ]] && target=$1 || die "多余参数: $1" ;;
    esac
    shift
done

[[ -z $target ]] && { list_all; exit 0; }

# ---------------------------------------------------------------------------
# 解析目标: PID 或 名称(模糊)
# ---------------------------------------------------------------------------
if [[ $target =~ ^[0-9]+$ ]]; then
    name_of_pid "$target"; rc=$?
    (( rc == 2 )) && die "PID $target 不存在"
    (( rc == 0 )) || die "PID $target 不是 supervisor 管理的进程 (试试 slog 看列表)"
    echo "${C_DIM}PID $target -> ${FOUND_NAME}${C_RESET}" >&2
    target=$FOUND_NAME
    match_mode=exact
else
    match_mode=fuzzy
fi

conf_line=""
while IFS=$'\t' read -r name cmd out err; do
    if [[ $match_mode == exact ]]; then
        [[ $name == "$target" ]] && { conf_line="$name	$cmd	$out	$err"; break; }
    else
        # 优先精确，其次前缀/子串
        if [[ $name == "$target" ]]; then
            conf_line="$name	$cmd	$out	$err"; break
        elif [[ -z $conf_line && ( $name == "$target"* || $name == *"$target"* ) ]]; then
            conf_line="$name	$cmd	$out	$err"
        fi
    fi
done < <(parse_confs)

[[ -n $conf_line ]] || die "找不到进程 '$target'。可用的进程:
$(parse_confs | cut -f1 | sed 's/^/  /')"

IFS=$'\t' read -r name cmd logout logerr <<< "$conf_line"
logfile=$([[ $stream == stderr ]] && printf '%s' "$logerr" || printf '%s' "$logout")

[[ -n $logfile ]] || die "$name 未配置 $stream 日志"
[[ -e $logfile ]] || die "日志文件不存在: $logfile"
[[ -r $logfile ]] || die "无权限读取: $logfile"

if find_pid "$cmd"; then
    status="${C_GREEN}RUNNING${C_RESET} pid=$FOUND_PID"
else
    status="${C_RED}STOPPED${C_RESET}"
fi
echo "${C_BOLD}${C_CYAN}$name${C_RESET} [$status] ${C_DIM}$stream -> $logfile${C_RESET}" >&2

# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
if (( all_rotated )); then
    # 搜索包含轮转在内的所有日志，按时间从旧到新
    mapfile -t files < <(ls -1tr "$logfile" "$logfile".* 2>/dev/null)
    (( ${#files[@]} )) || files=("$logfile")
    echo "${C_DIM}搜索 ${#files[@]} 个文件(含轮转)${C_RESET}" >&2
    if [[ -n $pattern ]]; then
        grep -inH --color=always -E "$pattern" "${files[@]}"
    else
        cat "${files[@]}"
    fi
    exit $?
fi

if (( pager )); then
    if [[ -n $pattern ]]; then
        grep -in --color=always -E "$pattern" "$logfile" | less -R +G
    else
        less -R +G "$logfile"
    fi
    exit $?
fi

if (( follow )); then
    if [[ -n $pattern ]]; then
        tail -n "$lines" -F "$logfile" | grep --line-buffered -i --color=always -E "$pattern"
    else
        tail -n "$lines" -F "$logfile"
    fi
else
    if [[ -n $pattern ]]; then
        tail -n "$lines" "$logfile" | grep -i --color=always -E "$pattern"
    else
        tail -n "$lines" "$logfile"
    fi
fi
