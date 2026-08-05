# bash completion for slog
#
# 位置: ~/.local/share/bash-completion/completions/slog
# bash-completion 会在首次敲 `slog <TAB>` 时按需加载本文件，无需改 .bashrc。

_slog() {
    local cur prev
    cur=${COMP_WORDS[COMP_CWORD]}
    prev=${COMP_WORDS[COMP_CWORD-1]}

    # 需要参数的选项：给点常用值当提示
    case $prev in
        -n|--lines)
            mapfile -t COMPREPLY < <(compgen -W "50 100 200 500 1000 5000" -- "$cur")
            return ;;
        -g|--grep)
            mapfile -t COMPREPLY < <(compgen -W "error panic FATAL WARN timeout refused" -- "$cur")
            return ;;
    esac

    # 选项补全
    if [[ $cur == -* ]]; then
        mapfile -t COMPREPLY < <(compgen -W "
            -e --stderr
            -o --stdout
            -n --lines
            -g --grep
            -A --all
            -p --pager
            -f --follow
            -l --list
            -h --help
            --names
        " -- "$cur")
        return
    fi

    # 已经给过进程名/PID 了就不再补第二个
    local w seen=0
    for w in "${COMP_WORDS[@]:1:COMP_CWORD-1}"; do
        [[ $w == -* ]] && continue
        # 跳过 -n / -g 的参数值
        [[ $prev == -n || $prev == --lines || $prev == -g || $prev == --grep ]] && continue
        seen=1
    done
    (( seen )) && return

    # 补全进程名（由 slog --names 提供，与脚本共用同一份 conf 解析）
    local names
    names=$(slog --names 2>/dev/null) || return
    mapfile -t COMPREPLY < <(compgen -W "$names" -- "$cur")
}

complete -F _slog slog
