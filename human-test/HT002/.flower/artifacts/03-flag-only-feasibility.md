# 03 — "只改编译 flag" 可行性判定

日期:2026-09-07 · 机器:Darwin 25.2.0 arm64 · SDK:`/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`
试验场地:`/tmp/cppide-flagtest`(仓库 `cp -R` 副本)· **`/Users/hechenyu/explore/test-ide/cppide` 全程未被触碰**

---

## 结论(先说结果)

**纯 flag 方案不可行。** 4 个阻断点里,只有 `::_exit` 那个能被纯 flag 解决;
`::sigemptyset` 那个**在 flag 层面无解**——原因是任务书里的核心线索**猜错了守卫条件**。

但**方案 X(shim 头 + `-include`)可行,且可以做成"只改 Makefile 一个文件"**:
让 Makefile 自己把 shim 生成到 `build/`(不入库),仓库的版本控制 diff 就只有 `Makefile` 一个文件。
实测 `make` 退出码 0,产物 `Mach-O 64-bit executable arm64`,`./cppide --help` 正常输出,
`make check-headers` 也照样 OK。

---

## 一、SDK 头文件原文:守卫条件的实际形态

任务书的猜测是宏被 `#if !defined(_POSIX_C_SOURCE) || defined(_DARWIN_C_SOURCE)` 守卫。
**这个猜测对 `sys/signal.h` 里的一大批宏成立,但对 `sigemptyset` 不成立。**

`sigemptyset` 这几个宏根本不在 `sys/signal.h` 里,而在**上层的 `/usr/include/signal.h`**,
守卫是 `#ifndef _ANSI_SOURCE` —— 一个和 `_POSIX_C_SOURCE` / `_DARWIN_C_SOURCE` 完全无关的开关。

`/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/signal.h`:

```c
 80  #ifndef	_ANSI_SOURCE
 81  __BEGIN_DECLS
 ..
 87  int	sigaction(int, const struct sigaction * __restrict,
 88  	    struct sigaction * __restrict);
 89  int	sigaddset(sigset_t *, int);
 ..
 92  int	sigemptyset(sigset_t *);          <-- 真实函数原型就在这儿
 93  int	sigfillset(sigset_t *);
 ..
113  __END_DECLS
114
115  /* List definitions after function declarations, or Reiser cpp gets upset. */
116  __header_always_inline int
117  __sigbits(int __signo)
118  {
119      return __signo > __DARWIN_NSIG ? 0 : (1 << (__signo - 1));
120  }
121
122  #define	sigaddset(set, signo)	(*(set) |= __sigbits(signo), 0)
123  #define	sigdelset(set, signo)	(*(set) &= ~__sigbits(signo), 0)
124  #define	sigismember(set, signo)	((*(set) & __sigbits(signo)) != 0)
125  #define	sigemptyset(set)	(*(set) = 0, 0)      <-- 罪魁
126  #define	sigfillset(set)		(*(set) = ~(sigset_t)0, 0)
127  #endif	/* !_ANSI_SOURCE */
```

**关键点:第 80 行的 `#ifndef _ANSI_SOURCE` 同时罩住了"原型"(92 行)和"宏"(125 行)。**
它们是**同生共死**的 —— 想用特性测试宏关掉第 125 行的宏,就必然连第 92 行的原型一起关掉,
于是 `::sigemptyset` 从"语法错误"变成"global namespace 里没这个成员",一样编不过。
这就是纯 flag 路线的死结。

（对照:`sys/signal.h` 里确实有 18 处 `_POSIX_C_SOURCE`/`_DARWIN_C_SOURCE` 守卫,
比如 `sigmask()`、`sigvec()`、`sys_siglist`,但 `sigemptyset` 一个都不在其中。
`grep -rn "define[[:space:]]*sigemptyset" $SDK/usr/include/` 只命中 `signal.h:125` 这一处。）

### 预处理器层面的直接验证

```
$ printf '#include <signal.h>\n' | c++ -std=c++17 -x c++ - -dM -E $FLAGS | grep -c '^#define sigemptyset'

flags=[]                                      sigemptyset_macro_defined=1
flags=[-D_POSIX_C_SOURCE=200809L]             sigemptyset_macro_defined=1   <-- 线索证伪
flags=[-D_XOPEN_SOURCE=700]                   sigemptyset_macro_defined=1
flags=[-D_XOPEN_SOURCE=600]                   sigemptyset_macro_defined=1
flags=[-D_ANSI_SOURCE]                        sigemptyset_macro_defined=0   <-- 唯一能关掉的
flags=[-D_POSIX_C_SOURCE=200809L -D_ANSI_SOURCE] sigemptyset_macro_defined=1
```

最后一行的反直觉结果来自 `sys/cdefs.h`:`_POSIX_C_SOURCE` 与 `_ANSI_SOURCE` 互斥时前者胜出,
所以"用 `_ANSI_SOURCE` 关宏、再用 `_POSIX_C_SOURCE` 找回原型"这条补偿路线**从一开始就走不通**。

---

## 二、试验方法

副本:`cp -R /Users/hechenyu/explore/test-ide/cppide /tmp/cppide-flagtest`
（副本继承了前一轮已生效的两处修复:`make clean` 干掉误提交的 Linux `.o`;Makefile 第 34 行的
`CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED` 已取消注释。）

每轮:

```sh
BASE="-std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter -MMD -MP"
make clean && make -k CXXFLAGS="$BASE <本轮附加 flag>"
```

用 `CXXFLAGS=` 覆盖而不是 `CPPFLAGS=`:后者会把 Makefile 里 `+=` 累积的 `-Isrc` /
`-D_XOPEN_SOURCE_EXTENDED` / brew include path 全部冲掉。二者最终都落在同一条编译命令行上,等价。
用 `-k` 让 make 不在第一个失败的 TU 上停下,以便一次看全所有阻断点
（`src/proc.cpp` 字典序在 `src/ui.cpp` 之前,不加 `-k` 时 ui.cpp 的错误根本不会暴露）。

**全程没有修改任何 `src/*.cpp`、`src/*.h`、`main.cpp` —— 副本里也没有。**

---

## 三、逐个组合的实测结果

| # | 附加 flag | EXIT | 卡在哪 |
|---|---|---|---|
| baseline | (无) | 2 | `proc.cpp:125` + `:217` `expected unqualified-id`;`ui.cpp:69` `no member named '_exit' in the global namespace` |
| E | `-include unistd.h` | 2 | `_exit` **已修好**;只剩 `proc.cpp:125` + `:217` 两处 `expected unqualified-id` |
| A | `-include unistd.h -D_POSIX_C_SOURCE=200809L` | 2 | `sigemptyset` **纹丝不动**,并**新弄坏** `util.cpp:471,472` `no member named 'st_mtimespec' in 'stat'` |
| B | `-include unistd.h -D_XOPEN_SOURCE=700` | 2 | 与 A 完全同构(cdefs.h 把 `_XOPEN_SOURCE=700` 归一成 `_POSIX_C_SOURCE=200809L`) |
| C | `-include unistd.h -D_XOPEN_SOURCE=600` | 2 | 比 A 更糟:`sigemptyset` 依旧,外加 `O_CLOEXEC` 未声明(`textbuf.cpp:545,621`;`util.cpp:488,526,555`)、`F_DUPFD_CLOEXEC` 未声明(`proc.cpp:106`)、`st_mtimespec`。10 条 error |
| D1 | `-include unistd.h -D_POSIX_C_SOURCE=200809L -D_DARWIN_C_SOURCE` | 2 | 补偿有效——`st_mtimespec` 回来了,回到"只剩 2 条 `sigemptyset`"。**等价于 E,没有前进** |
| D2 | `-include unistd.h -D_ANSI_SOURCE` | 2 | 宏确实没了,但原型也没了:`proc.cpp:125: no member named 'sigemptyset' in the global namespace`、`struct sigaction` 不完整类型、`SIG_SETMASK` 未声明、`main.cpp:367 setenv` 缺失,连 libc++ 自己的 `__thread/support/pthread.h:198` 都报 `nanosleep` 未声明。**44 条 error** |
| F | `-include unistd.h -D_USER_SIGNAL_H`(预定义 `signal.h` 的 include guard,让整个头文件空转) | 2 | **26 条 error**:`main.cpp:52/53/65/341` `reference to unresolved using declaration`、`excess elements in scalar initializer` 等 |

### 其余纯 flag 小花招(单文件 probe,`::sigemptyset(s)`)

```c
// /tmp/probe.cpp
#include <signal.h>
int f(sigset_t*s){return ::sigemptyset(s);}
```

| flag | rc | 首条错误 |
|---|---|---|
| `-Usigemptyset` | 1 | `error: expected unqualified-id` —— `-U` 在 `#include` **之前**生效,头文件之后又 `#define` 回来 |
| `-Dsigemptyset=sigemptyset`(对象式自引用,想靠 blue paint 挡住) | 1 | `error: expected unqualified-id` —— 头文件的 `#define` 是**重定义**,新定义胜出 |
| `-Dsigemptyset(x)=sigemptyset(x)`(函数式自引用) | 1 | 同上,重定义照样胜出 |
| `-D_ANSI_SOURCE -D_POSIX_C_SOURCE=200809L` | 1 | `error: unknown type name 'sigset_t'` —— 两个开关互斥,`_POSIX_C_SOURCE` 赢,宏回来 |
| `-D_NONSTD_SOURCE` | 1 | `sys/cdefs.h:685: error: "Can't define _NONSTD_SOURCE when only UNIX conformance is available."` |

补充:`grep -rn "undef[[:space:]]*sigemptyset" $SDK/usr/include/` **零命中** —— SDK 里没有任何现成头文件
可以被 `-include` 借来当 shim 用。

### 为什么"纯 flag"在原理上就走不通

要让 `::sigemptyset` 编过,必须同时满足两件事:
1. 名字 `sigemptyset` **不是宏**;
2. 名字 `sigemptyset` **在 global namespace 里有声明**。

在 Apple SDK 里,这两件事被同一个 `#ifndef _ANSI_SOURCE` 块(第 80–127 行)绑死:
关掉块 → 1 满足、2 不满足(D2);开着块 → 2 满足、1 不满足(baseline/A/B/C/D1)。
命令行 `-D`/`-U` 只能在**所有 `#include` 之前**生效,没有任何"在头文件之后再 `#undef`"的 flag。
**唯一能插到"头文件之后、源码之前"的钩子就是 `-include <某个文件>`,而那必然要求存在一个文件。**

---

## 四、方案 X(shim 头 + `-include`):可行

### X-1:shim 作为一个入库的头文件

`/tmp/cppide-flagtest/src/macos-compat.h`(21 行),Makefile 加 `-include unistd.h -include macos-compat.h`
(靠已有的 `-Isrc` 解析):

```
###### PLAN X  EXIT=0
   [errors: 0]  [warnings: 2]
./cppide: Mach-O 64-bit executable arm64
```

原理:`-include` 的文件在主 TU 之前被处理,shim 先 `#include <signal.h>` 把宏拉进来再 `#undef` 掉;
`signal.h` 自带 include guard `_USER_SIGNAL_H`,源码后面再 `#include <signal.h>` 不会把宏重新定义回来,
于是 `::sigemptyset` 干净地解析到 libSystem 里真实存在的 `int sigemptyset(sigset_t *)`。

**注意副作用:** 放进 `src/` 会被 `HDR := $(wildcard src/*.h)` 捞进 `check-headers` 验收门
(实测能过,但等于给那个门增加了一个平台专属头)。X-2 没有这个问题。

### X-2(推荐):shim 由 Makefile 生成到 `build/`,**版本控制 diff 只有 Makefile 一个文件**

实测(不带任何命令行覆盖,直接 `make clean && make`):

```
###### Y: Makefile-only(自生成 shim)  EXIT=0
[errors: 0] [warnings: 2]
./cppide: Mach-O 64-bit executable arm64

$ ./cppide --help
cppide 0.1.0 —— 跑在终端里的 C/C++ 单文件编辑器(编辑 + 一键编译运行 + AI 辅助)
...
$ make check-headers
check-headers: OK (15 个头文件)   EXIT=0
```

Makefile 改动(4 处,均在构建文件内,`src/` 一个字节没动):

```diff
@@ ifeq ($(UNAME_S),Darwin) 块内 @@
-  # CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
+  CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
+  # macOS 兼容垫片(由本 Makefile 生成到 build/,不入库):规则见下方。
+  MACSHIM   := build/macos-compat.h
+  CPPFLAGS += -include $(MACSHIM) -include unistd.h

@@ all: $(BIN) 之后 @@
+# Apple SDK 的 /usr/include/signal.h 在函数原型之后又把 sigemptyset 等定义成函数式宏
+# (仅被 #ifndef _ANSI_SOURCE 守卫),于是 `::sigemptyset(&s)` 展开成 `::(*(&s)=0,0)`。
+# 这里生成一个只做 #undef 的垫片头,用 -include 强制前置。
+$(MACSHIM):
+	@mkdir -p $(dir $@)
+	@printf '#include <signal.h>\n#undef sigemptyset\n#undef sigfillset\n#undef sigaddset\n#undef sigdelset\n#undef sigismember\n' > $@

@@ 编译规则 @@
-%.o: %.cpp
+%.o: %.cpp $(MACSHIM)

@@ clean @@
 clean:
+	rm -rf build
 	rm -f $(OBJ) $(DEP) $(BIN) $(DBGOBJ) $(DBGDEP) $(DBGBIN)
```

生成出来的 `build/macos-compat.h` 内容(6 行):

```c
#include <signal.h>
#undef sigemptyset
#undef sigfillset
#undef sigaddset
#undef sigdelset
#undef sigismember
```

（`sigfillset`/`sigaddset`/`sigdelset`/`sigismember` 一起 `#undef` 是防御性的:当前源码只用到
`::sigemptyset`,但这 5 个宏是同一批,以后谁写了 `::sigaddset` 会撞同一个坑。）

`-include unistd.h` 与 shim 是两件独立的事:前者补 `src/ui.cpp` 漏掉的 `<unistd.h>`(`::_exit`),
后者解 `sigemptyset`。两者都只动 Makefile。

**未做的事:** 以上改动**只存在于 `/tmp/cppide-flagtest`**,没有应用到
`/Users/hechenyu/explore/test-ide/cppide`。

---

## 五、遗留观察(不阻断构建)

- `brew --prefix ncurses` 返回 `/opt/homebrew/opt/ncurses`,但 `/opt/homebrew/opt/ncurses/lib`
  **不存在**(配方目录残留 / 未真正安装)。于是 Makefile 第 26–30 行加进去的 `-L` 让链接器吐
  `ld: warning: search path '/opt/homebrew/opt/ncurses/lib' not found`。
  最终链的是系统 ncurses,构建成功,但这个探测逻辑不够稳健(只判了 `brew --prefix` 的**退出码/输出非空**,
  没判目录是否真的存在)。
- `src/ui.cpp:1192:30: warning: ISO C++11 does not allow conversion from string literal to 'char *'`
  —— 唯一一条源码警告,不阻断。

---

## 六、最小改动集合(按档位)

| 档位 | 能否达成 | 说明 |
|---|---|---|
| **① 只碰构建 flag(纯 `-D`/`-U`,不新增任何文件)** | ❌ **做不到** | `sigemptyset` 的宏与原型被同一个 `#ifndef _ANSI_SOURCE` 绑死,命令行宏只能在 `#include` 前生效,原理上无解。A/B/C/D1/D2/F 六组实测全部 EXIT=2 |
| **② 只碰构建文件(Makefile),但需要一个 `-include` 垫片文件** | ✅ **落在这一档** | Makefile 自生成 `build/macos-compat.h`,VCS diff 只有 `Makefile`。`make` EXIT=0,产物 arm64 Mach-O,`--help` 正常,`check-headers` OK |
| ③ 必须新增一个入库的 shim 头(`src/macos-compat.h`) | ✅ 可行但非必需 | 与 ② 等效,只是把生成物变成入库文件;代价是进了 `check-headers` 的 `HDR` 列表 |
| ④ 必须改源码 | 不必要 | `proc.cpp:125/217` 去掉 `::`(或改 `sigemptyset(...)`)、`ui.cpp` 补 `#include <unistd.h>` 才是真正的可移植性修复,但**不是让 macOS 构建通过的必要条件** |

**判定:落在第 ②档。** 任务标题问的"只改 Makefile 编译 flag、一行源码都不动能否构建成功"——
如果"只改 flag"严格解释为"只加 `-D`/`-U`",答案是**否**;
如果解释为"只改 Makefile 这一个文件、`src/` 一行不动",答案是**是**(需要 Makefile 顺手生成一个 6 行垫片头)。

从工程角度,④ 才是根治:`::sigemptyset` 的 `::` 是画蛇添足(C++ 里对 C 库函数加 `::` 限定本来就
容易撞上宏),`src/ui.cpp` 用了 `::_exit` 却不 include `<unistd.h>` 是实打实的头文件依赖缺失
(在 Linux 上靠传递包含侥幸编过)。但按本轮任务边界,源码未被修改。

---

## 附:本轮产生的临时文件(全在 /tmp)

- `/tmp/cppide-flagtest/` —— 仓库副本 + 上述 Makefile 改动(可直接 `make` 复现 EXIT=0)
- `/tmp/ft-*.txt` —— 每轮完整构建日志(baseline / A / B / C / D1 / D2 / E / F / X / Y)
- `/tmp/probe.cpp` —— 单文件宏 probe
