package internal

// PROBE-TEMP: RETAINED 时从 Play 全局结构递归扫描, 找出持有 Player 对象地址的路径。
// 修复1: reflect 从其他包访问未导出字段时 CanInterface()=false 会跳过子管理器内部字段,
//        用 reflect.NewAt+UnsafeAddr 绕过。
// 修复2: 对照组不再依赖 activePlayers(测试时可能为空), 改用 play.playerMgr(基础) +
//        BattlePassMgr.Mgr 首个元素(深层 map 遍历验证), 确保扫描器可靠性可判定。
// 修复3: 同时扫描 Player 基址 addr 与 包装基址 addr-8(dump 显示 Player 被嵌在 +8 前缀对象里)。
// 纯只读 reflect 扫描, 带 visited 防环 + 节点预算防跑飞。验证后删除。
import (
	"fmt"
	"reflect"
	"unsafe"
	// "wrangler_game/game/play/internal/mplayer" // PROBE-TEMP 探针注释(恢复赋值时取消注释)
)

const holderScanNodeBudget = 8000000

// scanHolder 从 play 全局实例出发, 查找哪个顶层字段可达 Player 对象(addr)或其包装基址(addr-8)。
// 采用【范围匹配】: 指针落在 [target, target+1152) 内即算命中(Player 分配大小 1064→size class 1152),
// 可捕获深内部指针持有者(如 &Player.SomeField)。对照组验证扫描器可靠性。
func (play *Play) scanHolder(_ int64, addr uintptr) string {
	if play == nil || addr == 0 {
		return "no-scan(play nil)"
	}
	pv := reflect.ValueOf(play).Elem()
	t := pv.Type()

	// 对照组1: play.playerMgr(基础字段可达性)
	basicControl := uintptr(0)
	if play.playerMgr != nil {
		basicControl = uintptr(unsafe.Pointer(play.playerMgr))
	}
	// 对照组2: BattlePassMgr.Mgr 首个元素(深层 map 遍历可达性, Mgr 有上万条不空)
	var deepControl uintptr
	if play.BattlePassMgr != nil {
		for _, v := range play.BattlePassMgr.Mgr {
			deepControl = uintptr(unsafe.Pointer(v))
			break
		}
	}

	findFromTop := func(target uintptr) (string, string, string) {
		// 返回 (目标路径, basicControl 命中, deepControl 命中)
		basicHit, deepHit := "", ""
		for i := 0; i < pv.NumField(); i++ {
			f := pv.Field(i)
			if !f.CanInterface() {
				continue
			}
			visited := make(map[uintptr]bool)
			budget := holderScanNodeBudget
			if reachableRange(f, target, 1152, visited, &budget) {
				return fmt.Sprintf("play.%s", t.Field(i).Name), basicHit, deepHit
			}
			if basicControl != 0 && basicHit == "" {
				visitedB := make(map[uintptr]bool)
				budgetB := holderScanNodeBudget
				if reachableRange(f, basicControl, 8, visitedB, &budgetB) {
					basicHit = "yes"
				}
			}
			if deepControl != 0 && deepHit == "" {
				visitedD := make(map[uintptr]bool)
				budgetD := holderScanNodeBudget
				if reachableRange(f, deepControl, 8, visitedD, &budgetD) {
					deepHit = "yes"
				}
			}
		}
		return "", basicHit, deepHit
	}

	// 目标1: Player 基址 addr(范围 1152)
	path1, basic1, deep1 := findFromTop(addr)
	// 目标2: 包装基址 (addr-8, 范围 1152)
	path2, basic2, deep2 := "", "", ""
	if addr > 8 {
		path2, basic2, deep2 = findFromTop(addr - 8)
	}

	return fmt.Sprintf("player-addr=[%v] wrapper-addr8=[%v] control[basic=%v/%v deep=%v/%v]",
		path1, path2, basic1, basic2, deep1, deep2)
}

// reachableRange 深度遍历 v 指向的对象图, 查找是否有指针落在 [target, target+span) 范围内。
func reachableRange(v reflect.Value, target uintptr, span uintptr, visited map[uintptr]bool, budget *int) bool {
	for v.IsValid() {
		if *budget <= 0 {
			return false
		}
		*budget--
		switch v.Kind() {
		case reflect.Ptr, reflect.Interface:
			if v.IsNil() {
				return false
			}
			if v.Kind() == reflect.Ptr {
				p := v.Pointer()
				if p >= target && p < target+span {
					return true
				}
				if visited[p] {
					return false
				}
				visited[p] = true
			}
			v = v.Elem()
		case reflect.Struct:
			for i := 0; i < v.NumField(); i++ {
				f, ok := fieldValue(v.Field(i))
				if !ok {
					continue
				}
				if reachableRange(f, target, span, visited, budget) {
					return true
				}
			}
			return false
		case reflect.Map:
			iter := v.MapRange()
			for iter.Next() {
				if reachableRange(iter.Value(), target, span, visited, budget) {
					return true
				}
			}
			return false
		case reflect.Slice, reflect.Array:
			for i := 0; i < v.Len(); i++ {
				if reachableRange(v.Index(i), target, span, visited, budget) {
					return true
				}
			}
			return false
		default:
			return false
		}
	}
	return false
}

func fieldValue(f reflect.Value) (reflect.Value, bool) {
	if f.CanInterface() {
		return f, true
	}
	if !f.CanAddr() {
		return f, false
	}
	f2 := reflect.NewAt(f.Type(), unsafe.Pointer(f.UnsafeAddr())).Elem()
	return f2, true
}

// registerProbeHolderScan 在 play 模块初始化时注册 holder 扫描回调
func (play *Play) registerProbeHolderScan() {
	// mplayer.ProbeOnRetained = play.scanHolder // PROBE-TEMP 探针注释(ProbeOnRetained 已注释)
}
