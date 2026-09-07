# 05 — 最终:补丁落地 / 构建 / 启动 / 取证

- 日期:2026-09-07
- 平台:macOS Darwin 25.2.0 (arm64)
- 仓库:`/Users/hechenyu/explore/test-ide/cppide`
- 前置报告:`03-flag-only-feasibility.md`(X-2 方案)、已验证副本 `/tmp/cppide-flagtest`

---

## A. 补丁应用(只改 `Makefile`)

按 X-2 方案改动 4 处,全部落在 Darwin 分支或受 `$(MACSHIM)` 空展开保护的位置。
落地后 `diff cppide/Makefile /tmp/cppide-flagtest/Makefile` → **完全一致**(IDENTICAL_TO_VERIFIED_COPY)。

### `git diff Makefile` 完整 diff(+14 / −2)

```diff
diff --git a/Makefile b/Makefile
index 2633c72..85062dc 100644
--- a/Makefile
+++ b/Makefile
@@ -31,7 +31,10 @@ ifeq ($(UNAME_S),Darwin)
   LDLIBS += -lncurses -lcurl -lpthread
   # 若 macOS 自带的 ncurses 头不肯给出宽字符原型(get_wch / add_wch / cchar_t 未声明),
   # 打开下面这行;Debian 的 ncursesw 头默认已 NCURSES_WIDECHAR=1,不需要它。
-  # CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
+  CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
+  # macOS 兼容垫片(由本 Makefile 生成到 build/,不入库):规则见下方。
+  MACSHIM   := build/macos-compat.h
+  CPPFLAGS += -include $(MACSHIM) -include unistd.h
 else
   # Linux:宽字符符号(add_wch/get_wch)只在 ncursesw 里,必须链 -lncursesw
   LDLIBS += -lncursesw -lcurl -lpthread
@@ -58,10 +61,18 @@ SYNFLAGS := $(filter-out -MMD -MP,$(CXXFLAGS))

 all: $(BIN)

+# Apple SDK 的 /usr/include/signal.h 在函数原型之后又把 sigemptyset 等定义成函数式宏
+# (仅被 #ifndef _ANSI_SOURCE 守卫),于是 `::sigemptyset(&s)` 展开成 `::(*(&s)=0,0)`。
+# 这里生成一个只做 #undef 的垫片头,用 -include 强制前置。
+$(MACSHIM):
+	@mkdir -p $(dir $@)
+	@printf '#include <signal.h>\n#undef sigemptyset\n#undef sigfillset\n#undef sigaddset\n#undef sigdelset\n#undef sigismember\n' > $@
+
+
 $(BIN): $(OBJ)
 	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)

-%.o: %.cpp
+%.o: %.cpp $(MACSHIM)
 	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c -o $@ $<

 # Wave 1 的验收门:每个头文件必须自给自足。
@@ -92,6 +103,7 @@ install: $(BIN)
 	install -m 0755 $(BIN) $(DESTDIR)$(PREFIX)/bin/$(BIN)

 clean:
+	rm -rf build
 	rm -f $(OBJ) $(DEP) $(BIN) $(DBGOBJ) $(DBGDEP) $(DBGBIN)

 -include $(DEP)
```

### 4 处改动逐条说明

| # | 改动 | 为什么 |
|---|------|--------|
| 1 | 取消注释 `CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED` | macOS 自带 `curses.h` 默认 `NCURSES_WIDECHAR=0`,不给 `get_wch/add_wch/cchar_t` 原型 |
| 2 | Darwin 分支加 `MACSHIM := build/macos-compat.h` + `CPPFLAGS += -include $(MACSHIM) -include unistd.h` | 垫片修 `src/proc.cpp` 的 `::sigemptyset` 宏冲突;`-include unistd.h` 修 `src/ui.cpp:69` 的 `::_exit` 缺声明 |
| 3 | 新增 `$(MACSHIM):` 规则(mkdir + printf 生成垫片头) | Apple SDK `/usr/include/signal.h` 在同一 `#ifndef _ANSI_SOURCE` 块里同时给出真实原型和同名函数式宏,纯 `-D`/`-U` 无解(6 组实测全失败),只能靠 `-include` 前置 `#undef` |
| 4 | `%.o: %.cpp` → `%.o: %.cpp $(MACSHIM)` 且 `clean` 加 `rm -rf build` | 让垫片在任何 `.o` 之前自动生成;`clean` 负责回收生成的 `build/` |

### Linux 路径未被污染(实测)

`MACSHIM` 只在 `ifeq ($(UNAME_S),Darwin)` 分支里定义,Linux 下为空:
- `%.o: %.cpp $(MACSHIM)` 空展开回 `%.o: %.cpp`
- `$(MACSHIM):` 空目标规则被 GNU make 静默忽略,不报 missing separator

实测 `make -n UNAME_S=Linux src/util.o`:

```
c++ -Isrc -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter -MMD -MP -c -o src/util.o src/util.cpp
```

无 `-include`、无 `-D_XOPEN_SOURCE_EXTENDED`、无 `-I/opt/homebrew/...`。**Linux 行为完全不变。**

**除 `Makefile` 外未改动仓库任何文件。**

---

## B. 构建

### B1. `make clean && make`

```
===== make clean =====
rm -rf build
rm -f src/ai.o src/aihttp.o src/app.o src/build.o src/config.o src/editor.o src/highlight.o
       src/json.o src/keys.o src/main.o src/panel.o src/proc.o src/textbuf.o src/ui.o src/util.o
       src/ai.d ... src/util.d cppide
       src/ai.dbg.o ... src/util.dbg.o src/ai.dbg.d ... src/util.dbg.d cppide-debug
CLEAN_EXIT=0

===== make =====
c++ -Isrc -I/opt/homebrew/opt/ncurses/include -D_XOPEN_SOURCE_EXTENDED \
    -include build/macos-compat.h -include unistd.h \
    -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter -MMD -MP -c -o src/ai.o src/ai.cpp
    (同样的 15 条:ai aihttp app build config editor highlight json keys main panel proc textbuf ui util)

src/ui.cpp:1192:30: warning: ISO C++11 does not allow conversion from string literal to 'char *' [-Wwritable-strings]
 1192 |     const int c = ::tigetnum("colors");
      |                              ^
1 warning generated.

c++ -L/opt/homebrew/opt/ncurses/lib -o cppide src/ai.o ... src/util.o -lncurses -lcurl -lpthread
ld: warning: search path '/opt/homebrew/opt/ncurses/lib' not found

MAKE_EXIT=0
```

**`echo $?` → 0。**

两条 warning 均为**非阻断**,且都不是本次补丁引入的:
- `src/ui.cpp:1192` `-Wwritable-strings`:源码把字符串字面量传给 `tigetnum(char*)`,属既有源码问题,按硬性约束**未改源码**。
- `ld: search path '/opt/homebrew/opt/ncurses/lib' not found`:`brew --prefix ncurses` 即使 formula 未安装也会返回路径,于是 Makefile 原有逻辑加了个不存在的 `-I`/`-L`。实际链接回落到系统 ncurses,无影响。

### B2. 产物

```
$ file cppide
cppide: Mach-O 64-bit executable arm64

$ ls -la cppide
-rwxr-xr-x  1 hechenyu  staff  486472 Sep  7 16:07 cppide
```

原来仓库里误提交的 Linux ELF aarch64 二进制已被替换为本机 Mach-O arm64。

生成的垫片:

```
$ ls -la build/
-rw-r--r--  1 hechenyu  staff  110 Sep  7 16:07 macos-compat.h

$ cat build/macos-compat.h
#include <signal.h>
#undef sigemptyset
#undef sigfillset
#undef sigaddset
#undef sigdelset
#undef sigismember
```

### B3. `./cppide --doctor`(退出码 0)

```
== cppide 自查(--doctor,非交互)==
版本: cppide 0.1.0 (C++17)

[终端]
stdin 是 tty  : 否
stdout 是 tty : 否
== cppide --doctor ==
TERM            : xterm-256color
LANG            : C.UTF-8
LC_ALL          : (未设置)
LC_CTYPE(生效)  : UTF-8
ncurses         : ncurses 6.0.20150808
MB_CUR_MAX      : 4(>1 才能输出中文)
sizeof(wchar_t) : 4
COLORS(terminfo): -2(尚未 initscr)
最小可用尺寸    : 60x16

[配置]
查找路径      : /Users/hechenyu/.config/cppide/config.json
文件存在      : 否
实际加载自    : (全部使用内置默认值)
api_key       : 未配置(AI 功能关闭,编辑/编译/运行不受影响)
model         : (未配置 —— AI 功能显示"未配置",不发请求)
chat url      : https://api.deepseek.com/v1/chat/completions
warnings (4 条):
  - 未找到配置文件 …:已使用默认设置,AI 功能已关闭。
  - 可执行 `cppide --print-config > …/config.json` 生成示例配置,再把 api_key 填进去。
  - AI 未配置:… 编辑、编译、运行功能均不受影响。
  - 未配置 model,… 编辑、语法高亮、编译、运行均不受影响。

[编译器]
cc  = cc  -> /usr/bin/cc      cflags: -O2 -std=c11 -Wall
cxx = c++ -> /usr/bin/c++     cxxflags: -O2 -std=c++17 -Wall
compile_timeout_ms: 30000   run_timeout_ms: 5000

[结论]
- 编译与运行功能就绪。
- AI 功能未启用(api_key 为空);编辑、编译、运行均不受影响。

DOCTOR_EXIT=0
```

**结论:编译与运行功能就绪。** 4 条 warning 全是"AI 未配置",预期内(仓库没有 `config.json`,也不该有)。

### B4. `make check-headers`

```
  src/ai.h
  … (15 个)
  src/util.h
check-headers: OK (15 个头文件)
CHECKHEADERS_EXIT=0
```

无 error、无 warning。15 个头文件全部自给自足。

### B5. `.gitignore` 与 `build/`

`cppide/.gitignore` 内容:

```
# 这是一份 human test 的**完整记录**仓库,不是发行版 —— 编译产物、二进制、
# 原始 transcript、工具输出转储都要留着,它们是这次运行的一部分。
# 唯一排除:填了真实 API key 的配置文件(只提交 config.sample.json)。
config.json
```

**`.gitignore` 没有覆盖 `build/`**(它只排除 `config.json`,而且注释明确说明本仓库**刻意**保留编译产物)。
因此 `git status --porcelain` 里出现 `?? build/`。

**如实报告,未改 `.gitignore`**(那属于额外改动)。`build/` 是本补丁生成的**构建产物目录**,只含 `macos-compat.h` 这一个由 Makefile 自动生成的垫片头,`make clean` 会 `rm -rf` 掉它。

---

## C. 真实 Terminal 窗口里启动界面

### C1. 启动

```
$ osascript -e 'tell application "Terminal" to do script "cd /Users/hechenyu/explore/test-ide/cppide && ./cppide src/main.cpp"'
tab 1 of window id 227030
OSASCRIPT_EXIT=0
```

osascript **未**被 Automation TCC 拒绝,无需回落到 `.command` 方案。
**未**对 front window 做任何 columns/rows/bounds 设置,未触碰用户已有窗口。

启动时刻 `2026-09-07 16:08:24`。

### C2. 启动的确实是仓库产物(不是 /tmp 副本)

```
$ lsof -a -p 94272 -d txt,cwd
cppide  94272  cwd  DIR  1,17     416  119502879  /Users/hechenyu/explore/test-ide/cppide
cppide  94272  txt  REG  1,17  486472  119551597  /Users/hechenyu/explore/test-ide/cppide/cppide

$ stat -f 'dev=%d inode=%i size=%z'
repo cppide : dev=16777233 inode=119551597 size=486472   <-- 运行中的就是这个
/tmp 副本   : dev=16777233 inode=119545500 size=486472
```

inode 不同,**运行的是仓库二进制**。

### C3. 截图:失败(两种方式都失败)

```
$ screencapture -x /Users/hechenyu/explore/test-ide/.flower/artifacts/cppide-ui.png
could not create image from display
EXIT=1

$ screencapture -x -o -l 227030 /Users/hechenyu/explore/test-ide/.flower/artifacts/cppide-ui.png
could not create image from window
EXIT=1

$ ls .flower/artifacts/*.png
(eval):1: no matches found     # 文件未生成
```

**没有生成任何 PNG。** 与上一轮同因:**屏幕录制(Screen Recording)TCC 未授权**,整屏与指定窗口两种捕获都被系统拒绝。
**未编造看图结果。**

### C4. 备用通道取证 —— AppleScript 读回窗口文本

`osascript -e 'tell application "Terminal" to get contents of tab 1 of window id 227030'`(OSA_WINID_EXIT=0)
还原出的界面**原样**如下:

```
   1 // main.cpp —— 进程入口
   2 //
   3 // 启动顺序(architecture.md §10,顺序不能错):
   4 //   setlocale(LC_ALL,"")            必须早于 initscr(否则中文宽度全按 1 算
   5 //   signal(SIGPIPE, SIG_IGN)        libcurl 与 runProcess 都需要
   6 //   装 endwin 安全网                 atexit + std::set_terminate + 致命信
   7 //   解析 argv
   8 //   ConfigLoader::load
   9 //   HttpChat::globalInit()          必须在任何线程启动之前
  10 //   构造 App(内部 Ui::init,再按需启动 AiService 线程)
  11 //   run()
  12 //   App 析构 -> AiService/Runner 析构(close + join,绝不 detach)-> Ui 析构
─[编译]─[运行]─[AI*]─[输入]─────────────────────────────────────────────────────
cppide 就绪 · 练习模式 · Ctrl-T 切模式 · Ctrl-B 编译 · Ctrl-R 运行 · F1 帮助
配置:未找到配置文件 /Users/hechenyu/.config/cppide/config.json:已使用默认设置,AI
功能已关闭。
配置:可执行 `cppide --print-config > /Users/hechenyu/.config/cppide/config.json`
生成示例配置,再把 api_key 填进去。
配置:AI 未配置:请在 /Users/hechenyu/.config/cppide/config.json 里填写
api_key,或设置环境变量 CPPIDE_API_KEY。编辑、编译、运行功能均不受影响。
配置:未配置 model,请按 DeepSeek 官方文档填写模型名。在此之前 AI
功能显示为"未配置"且不会发出任何请求;编辑、语法高亮、编译、运行均不受影响。

 练习模式  │ main.cpp │ 1:1 │ C++ │ AI 未配置                             F1帮助
```

这是一份**完整渲染**的 TUI:左侧行号栏 + `src/main.cpp` 正文、中部 `─[编译]─[运行]─[AI*]─[输入]─` 面板标签栏、消息区、底部状态栏(模式 / 文件名 / 光标 1:1 / 语言 C++ / AI 状态 / F1帮助)。
中文与全角字符正常显示(证明 `_XOPEN_SOURCE_EXTENDED` 宽字符路径生效)。

### C5. 进程存活

| 检查点 | 实际时刻 | 距启动 | PID | `ps` ELAPSED |
|--------|----------|--------|-----|--------------|
| 第 1 次 | 16:09:05 | +41s | **94272** | 00:40 |
| 第 2 次 | 16:09:35 | +71s | **94272** | 01:10 |

```
PID_COMPARE: T5=[94272] T35=[94272]
```

**两次 PID 一致(94272),进程持续存活。**

> 偏差如实说明:取证脚本在启动后 36 秒才开始跑(中间在跑 `git diff` 等命令),所以"第 1 次"实际落在 T+41s 而非 T+5s,"第 2 次"落在 T+71s 而非 T+35s。两次都**晚于**要求的时刻,存活性要求满足且更严格,但**没有 T+5s 这个精确时刻的数据点**。

第 2 次读回的窗口文本与第 1 次**逐字相同**,界面稳定未崩溃、未回落到 shell 提示符。

### C6. 监听端口

```
$ lsof -nP -iTCP -sTCP:LISTEN | grep -i cppide
LSOF_GREP_EXIT=1
```

**无输出**(grep 退出码 1 = 无匹配),符合预期:cppide 是纯终端 TUI,不监听任何端口。

---

## D. 重启验证

### D1. 杀进程

```
$ pgrep -fl cppide
94272 ./cppide src/main.cpp

$ pkill -f 'cppide src/main.cpp'
PKILL_EXIT=0

$ pgrep -fl cppide
PGREP_EXIT=1        # 无输出,确认已全部退出
CONFIRMED: no cppide process remains
```

### D2. 全新 shell 里重启(16:10:11)

```
$ osascript -e 'tell application "Terminal" to do script "cd /Users/hechenyu/explore/test-ide/cppide && ./cppide src/main.cpp"'
tab 1 of window id 227032
OSASCRIPT_EXIT=0
```

`do script` 每次都开一个**全新 Terminal 窗口 + 全新 shell**(新 window id 227032,与首次的 227030 不同)。

结果:

```
NEW_PID=[96040]  (old PID was 94272)
  PID  PPID ELAPSED COMMAND
96040 95738   00:14 ./cppide src/main.cpp

cppide  96040  cwd  DIR  1,17     416  119502879  /Users/hechenyu/explore/test-ide/cppide
cppide  96040  txt  REG  1,17  486472  119551597  /Users/hechenyu/explore/test-ide/cppide/cppide
```

新 PID **96040**(旧 94272),仍是**仓库二进制**(inode 119551597)。

窗口文本读回(window id 227032)与首次启动**逐字一致** —— 行号栏 + main.cpp 正文 + `─[编译]─[运行]─[AI*]─[输入]─` 面板栏 + 4 条配置提示 + 底部 ` 练习模式 │ main.cpp │ 1:1 │ C++ │ AI 未配置    F1帮助`。**界面重新渲染成功。**

重启后 `lsof -nP -iTCP -sTCP:LISTEN | grep -i cppide` 仍为空(exit 1)。

### D3. 重启命令的精确文本

```
cd /Users/hechenyu/explore/test-ide/cppide && ./cppide src/main.cpp
```

(在真实 Terminal 窗口里执行;本次通过
`osascript -e 'tell application "Terminal" to do script "cd /Users/hechenyu/explore/test-ide/cppide && ./cppide src/main.cpp"'` 送进新窗口)

---

## E. 收尾核对

### E1. `git status --porcelain` 完整输出(64 条)

```
 M Makefile
 M cppide
 D cppide-debug
 M src/ai.d
 D src/ai.dbg.d
 D src/ai.dbg.o
 M src/ai.o
 M src/aihttp.d
 D src/aihttp.dbg.d
 D src/aihttp.dbg.o
 M src/aihttp.o
 M src/app.d
 D src/app.dbg.d
 D src/app.dbg.o
 M src/app.o
 M src/build.d
 D src/build.dbg.d
 D src/build.dbg.o
 M src/build.o
 M src/config.d
 D src/config.dbg.d
 D src/config.dbg.o
 M src/config.o
 M src/editor.d
 D src/editor.dbg.d
 D src/editor.dbg.o
 M src/editor.o
 M src/highlight.d
 D src/highlight.dbg.d
 D src/highlight.dbg.o
 M src/highlight.o
 M src/json.d
 D src/json.dbg.d
 D src/json.dbg.o
 M src/json.o
 M src/keys.d
 D src/keys.dbg.d
 D src/keys.dbg.o
 M src/keys.o
 M src/main.d
 D src/main.dbg.d
 D src/main.dbg.o
 M src/main.o
 M src/panel.d
 D src/panel.dbg.d
 D src/panel.dbg.o
 M src/panel.o
 M src/proc.d
 D src/proc.dbg.d
 D src/proc.dbg.o
 M src/proc.o
 M src/textbuf.d
 D src/textbuf.dbg.d
 D src/textbuf.dbg.o
 M src/textbuf.o
 M src/ui.d
 D src/ui.dbg.d
 D src/ui.dbg.o
 M src/ui.o
 M src/util.d
 D src/util.dbg.d
 D src/util.dbg.o
 M src/util.o
?? build/
```

### E2. 逐条分类

| 类别 | 条数 | 明细 |
|------|------|------|
| **构建配置** | **1** | ` M Makefile` —— 本次唯一的人为改动 |
| **构建产物**(release,重新编译) | 30 | ` M src/*.o` ×15 + ` M src/*.d` ×15 —— Linux ELF 对象被 Mach-O arm64 覆盖 |
| **构建产物**(release 二进制) | 1 | ` M cppide` —— ELF aarch64 → Mach-O arm64 |
| **构建产物**(debug,被 `make clean` 删除) | 31 | ` D src/*.dbg.o` ×15 + ` D src/*.dbg.d` ×15 + ` D cppide-debug` |
| **构建产物**(新增未跟踪目录) | 1 | `?? build/` —— 只含自动生成的 `macos-compat.h`;`.gitignore` 未覆盖(见 B5) |
| **源码** | **0** | 无 |
| 合计 | **64** | |

**源码类改动 = 0 条。**

### E3. `git diff -- src/ main.cpp README.md`

**不为空 —— 14778 字节。但 100% 是仓库里已跟踪的编译产物,零源码。**

```
$ git diff --name-only -- src/ main.cpp README.md | awk -F. '{print $NF}' | sort | uniq -c
  30 d
  30 o
```

只有 30 个 `.d` + 30 个 `.o`,**没有任何 `.cpp` / `.h`**。
(注:仓库根目录没有 `main.cpp`,入口是 `src/main.cpp`。)

真正的源码 diff 为**精确 0 字节**:

```
$ git diff -- 'src/*.cpp' 'src/*.h' main.cpp README.md config.sample.json | wc -c
0
```

全仓库范围内,排除 `.o`/`.d`/二进制后唯一被改的跟踪文件:

```
$ git diff --name-only | grep -Ev '\.(o|d)$' | grep -v '^cppide'
Makefile
```

**`src/*.cpp`、`src/*.h`、`README.md`、`config.sample.json` 一律未动,符合硬性约束。**

> 说明:`git diff -- src/ …` 之所以非空,是因为本仓库**刻意把 `.o`/`.d` 编译产物提交进了 git**(`.gitignore` 注释里写明"编译产物、二进制…都要留着")。重新编译必然让它们变化。这不是源码改动。

### E4. shell 配置 mtime(基准 2026-09-07 15:31:38)

```
2026-09-02 22:10:46  /Users/hechenyu/.zshrc
2026-03-22 16:41:01  /Users/hechenyu/.zprofile
2025-11-15 22:09:46  /Users/hechenyu/.profile
2025-11-15 22:09:46  /Users/hechenyu/.zshenv
(~/.bash_profile、~/.bashrc 不存在)
```

**全部早于 2026-09-07 15:31:38**(最新的 `.zshrc` 也在 5 天前)。**未改动任何 shell 配置 / PATH。**

### E5. 工作区目录

```
$ ls -a /Users/hechenyu/explore/test-ide
.  ..  .flower  cppide  runs
```

**与预期一致**,无多余条目。

### E6. 依赖目录

本项目**零第三方依赖**(只用系统 ncurses + libcurl + pthread,全部来自 macOS SDK,未安装任何包)。
本次唯一新增目录是 `cppide/build/`,**在 `cppide/` 内**,内容仅 `macos-compat.h`(110 字节,由 Makefile 生成),`make clean` 自动回收。
**未执行任何 `brew install` / `npm i -g` / `cargo install` / `sudo` / `pip install`。**

---

## 未做到 / 偏差(如实)

1. **截图失败** —— `screencapture` 整屏与指定窗口两种方式都被拒(`could not create image from display` / `could not create image from window`,exit 1),屏幕录制 TCC 未授权。**未生成 PNG,未编造看图内容。** 已用 AppleScript 读回窗口文本作为等效取证(C4)。
2. **存活检查时刻偏移** —— 要求 T+5s / T+35s,实际落在 T+41s / T+71s(取证脚本启动晚了 36 秒)。两次都晚于要求时刻,存活结论更强,但缺 T+5s 精确数据点。
3. **`git diff -- src/ main.cpp README.md` 非空** —— 要求"必须为空",实际 14778 字节。原因是仓库把 `.o`/`.d` 编译产物纳入了版本控制,重新编译必然使其变化。**源码(`*.cpp`/`*.h`/`README.md`/`config.sample.json`)diff 精确为 0 字节**,约束的实质(不改源码)已满足。
4. **`?? build/`** —— `.gitignore` 未覆盖 `build/`,按要求**未去修改 `.gitignore`**,如实报告。

其余全部达成。

---

## 关键文件路径

- 补丁文件:`/Users/hechenyu/explore/test-ide/cppide/Makefile`
- 生成的垫片:`/Users/hechenyu/explore/test-ide/cppide/build/macos-compat.h`
- 可执行产物:`/Users/hechenyu/explore/test-ide/cppide/cppide`(Mach-O arm64,486472 字节)
- 构建日志:`/tmp/cppide-build.log`
- 取证日志:`/tmp/cppide-forensics.log`、`/tmp/cppide-restart.log`
- 参照副本:`/tmp/cppide-flagtest/Makefile`(与仓库 Makefile 一致)
