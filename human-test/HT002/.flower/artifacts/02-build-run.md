# 02 — macOS 构建与运行验证

日期:2026-09-07 · 机器:Darwin 25.2.0 arm64 · 仓库:`/Users/hechenyu/explore/test-ide/cppide` @ d23d636 (main)

---

## 结论(先说结果)

**仓库在 macOS 上构建失败,且失败原因无法只靠 Makefile / 编译 flag 修复。**

任务书里预判的两个阻断点都被证实并已处理,但在它们之后暴露出**第三、第四个此前未记录的阻断点**,
两者都是 `src/` 里的源码可移植性缺陷。按任务边界(不许改仓库源码,发现必须改源码就停下报告),
我**没有修改任何源码**,在此报告。

为了给出确定性的结论,我在 `/tmp/cppide-poc`(仓库副本,**仓库本身未被触碰**)里施加了 2 处
最小源码补丁,证明:**这两处就是全部剩余阻断点**,补上之后整个项目在 macOS arm64 上
干净编译、链接、启动,TUI 正常渲染。

---

## A. 构建

### A1. 基线

```
$ git -C /Users/hechenyu/explore/test-ide/cppide status --porcelain
(无输出 — working tree 干净)
$ git rev-parse HEAD
d23d6367c02b4153c9f7d661f333dbd83153e8fe
```

仓库里提交的产物确认为 Linux ELF:

```
$ file cppide cppide-debug src/main.o
cppide:       ELF 64-bit LSB pie executable, ARM aarch64 ... for GNU/Linux 3.7.0
cppide-debug: ELF 64-bit LSB pie executable, ARM aarch64 ... with debug_info
src/main.o:   ELF 64-bit LSB relocatable, ARM aarch64
```

### A2. `make clean`

```
$ make clean
rm -f src/ai.o ... src/util.o  src/ai.d ... src/util.d  cppide
       src/ai.dbg.o ... src/util.dbg.o  src/ai.dbg.d ... src/util.dbg.d  cppide-debug
EXIT=0
```

删除的**被 git 跟踪**的文件共 **62 个**,全部是构建产物:

| 类型 | 数量 |
|---|---|
| `src/*.o`(release 目标文件,ELF aarch64) | 15 |
| `src/*.dbg.o`(debug 目标文件,ELF aarch64) | 15 |
| `src/*.d`(release 依赖文件) | 15 |
| `src/*.dbg.d`(debug 依赖文件) | 15 |
| `cppide` / `cppide-debug`(ELF aarch64 可执行) | 2 |

### A3. Makefile 改动

改动前先 Read 确认:Makefile 第 34 行,位于 `ifeq ($(UNAME_S),Darwin)` 块内。

```diff
@@ -34 +34 @@ ifeq ($(UNAME_S),Darwin)
-  # CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
+  CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
```

**为什么改**:macOS SDK 的 `curses.h` 第 173-179 行把 `NCURSES_WIDECHAR` 默认设为 0,
而 `add_wch` / `get_wch` / `waddnwstr` / `cchar_t` 全部锁在 `#if NCURSES_WIDECHAR` 里。
第 174 行的判据是 `#if defined(_XOPEN_SOURCE_EXTENDED) || (_XOPEN_SOURCE >= 500)`,
所以定义该宏是让 macOS 头暴露宽字符 API 的正规开关。

实测效果(仅此一处差异,无副作用):

```
$ c++ -Isrc -std=c++17 -fsyntax-only src/ui.cpp          # 不带 flag
src/ui.cpp:69:5:   error: no member named '_exit' in the global namespace
src/ui.cpp:274:7:  error: no member named 'waddnwstr' in the global namespace
src/ui.cpp:331:62: error: no member named 'waddnwstr' ...
src/ui.cpp:337:56: error: no member named 'waddnwstr' ...
src/ui.cpp:340:9:  error: no member named 'waddnwstr' ...
src/ui.cpp:343:9:  error: no member named 'waddnwstr' ...
src/ui.cpp:586:20: error: no member named 'wget_wch' ...
src/ui.cpp:594:21: error: no member named 'wget_wch' ...

$ c++ -Isrc -D_XOPEN_SOURCE_EXTENDED -std=c++17 -fsyntax-only src/ui.cpp   # 带 flag
src/ui.cpp:69:5: error: no member named '_exit' in the global namespace     # 只剩这一个
```

所有宽字符错误消失 —— 任务书判定正确,这个 flag 是必需且有效的。

### A4. `make`

```
$ make
c++ -Isrc -I/opt/homebrew/opt/ncurses/include -D_XOPEN_SOURCE_EXTENDED -std=c++17 -O2 \
    -Wall -Wextra -Wno-unused-parameter -MMD -MP -c -o src/ai.o src/ai.cpp
... (ai/aihttp/app/build/config/editor/highlight/json/keys/main/panel 共 11 个 TU 编译通过) ...
c++ ... -c -o src/proc.o src/proc.cpp
src/proc.cpp:125:9: error: expected unqualified-id
  125 |       ::sigemptyset(&sa.sa_mask);
      |         ^
/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/signal.h:125:26:
      note: expanded from macro 'sigemptyset'
  125 | #define sigemptyset(set)        (*(set) = 0, 0)
src/proc.cpp:217:7: error: expected unqualified-id
  217 |     ::sigemptyset(&empty);
2 errors generated.
make: *** [src/proc.o] Error 1
```

**退出码:2(失败)**

### A5. 迭代 / 根因分析(只用编译 flag,未改源码)

把全部 15 个 TU 逐个 `-fsyntax-only` 扫一遍,确定剩余阻断点的完整清单:

```
$ for f in src/*.cpp; do c++ -Isrc -D_XOPEN_SOURCE_EXTENDED -std=c++17 -fsyntax-only $f; done
===== src/proc.cpp =====
src/proc.cpp:125:9: error: expected unqualified-id
src/proc.cpp:217:7: error: expected unqualified-id
===== src/ui.cpp =====
src/ui.cpp:69:5: error: no member named '_exit' in the global namespace
```

只剩两处,均与本次 flag 改动**无关**(不带 flag 也同样报错):

#### 阻断点 3 — `src/proc.cpp:125` / `:217` — `::sigemptyset(...)`

macOS `signal.h` 在函数声明之后又把 `sigemptyset` 定义成**函数式宏**
(第 122-126 行,仅由 `#ifndef _ANSI_SOURCE` 保护)。预处理器不认识 C++ 作用域,
`::sigemptyset(x)` 会被展开成 `::(*(&x) = 0, 0)`,语法错误。
Linux/glibc 只提供函数、不提供该宏,所以这段代码在 Linux 上没问题。

**无法用编译 flag 绕过,已实测:**

```
$ c++ -Isrc -D_XOPEN_SOURCE_EXTENDED -Usigemptyset -std=c++17 -fsyntax-only src/proc.cpp
src/proc.cpp:125:9: error: expected unqualified-id     # -U 对头文件后定义的宏无效
src/proc.cpp:217:7: error: expected unqualified-id
```

唯一能抑制该宏的 feature-test 宏是 `_ANSI_SOURCE`,但它同时会隐藏 `sigaction`/
`sigprocmask` 等本文件必需的 POSIX API,不可用。

**修法(需要改源码,我没有改)**:把 `::sigemptyset(` 的 `::` 去掉即可 —— 宏展开
`(*(&sa.sa_mask) = 0, 0)` 本身是合法表达式,两处,共 2 行。

#### 阻断点 4 — `src/ui.cpp:69` — `::_exit(128 + sig)`

`ui.cpp` 包含了 `<curses.h>` / `<csignal>` / `<cstdlib>` 等,但**没有 `<unistd.h>`**,
而 `_exit` 由 `<unistd.h>` 声明。Linux 上靠头文件间接传递侥幸可见,macOS 上不可见。

**这一处可以只用编译 flag 修好,已实测通过:**

```
$ c++ -Isrc -D_XOPEN_SOURCE_EXTENDED -include unistd.h -std=c++17 -fsyntax-only src/ui.cpp
(无输出,rc=0)
```

但因为阻断点 3 无论如何都需要源码改动,单独加 `-include unistd.h` 并不能让构建成功,
属于无意义的 Makefile 噪音,故**未加入 Makefile**。

**修法(需要改源码,我没有改)**:`ui.cpp` 加一行 `#include <unistd.h>`。

### A6. 验证性构建(在 /tmp 副本上做,仓库未被触碰)

为确认上述两处是**全部**剩余阻断点,把仓库复制到 `/tmp/cppide-poc`,只施加 2 处最小补丁:

* `src/proc.cpp`:2 处 `::sigemptyset(` → `sigemptyset(`
* `src/ui.cpp`:增加 `#include <unistd.h>`

```
$ cd /tmp/cppide-poc && make clean && make
... 15 个 TU 全部编译通过 ...
src/ui.cpp:1193:30: warning: ISO C++11 does not allow conversion from string literal
                             to 'char *' [-Wwritable-strings]      # 仅警告
c++ -L/opt/homebrew/opt/ncurses/lib -o cppide src/*.o -lncurses -lcurl -lpthread
ld: warning: search path '/opt/homebrew/opt/ncurses/lib' not found  # 仅警告(见下)
构建成功
```

产物:

```
$ file cppide
cppide: Mach-O 64-bit executable arm64
$ ls -la cppide
-rwxr-xr-x  1 hechenyu  wheel  486424 Sep  7 15:46 cppide
```

关于任务书里的"次要噪音":`brew --prefix ncurses` 对未安装的 formula 仍返回
`/opt/homebrew/opt/ncurses` 且 rc=0,Makefile 因此加上了指向不存在目录的 `-I`/`-L`。
实测**只产生一条 ld warning,不影响构建**(系统 `/usr/lib` 的 ncurses 正常链上),
按任务书"只有在真的导致构建失败时才处理",**未处理**。

### A7. `--doctor`

```
$ ./cppide --doctor        # /tmp/cppide-poc 的产物
== cppide 自查(--doctor,非交互)==
版本: cppide 0.1.0 (C++17)
[终端] stdin 是 tty:否   stdout 是 tty:否
TERM: xterm-256color   LANG: C.UTF-8   LC_CTYPE(生效): UTF-8
ncurses: ncurses 6.0.20150808
MB_CUR_MAX: 4(>1 才能输出中文)   sizeof(wchar_t): 4
最小可用尺寸: 60x16
[配置] 未找到 ~/.config/cppide/config.json → 全部使用内置默认值;api_key 未配置(AI 关闭)
[编译器] cc = /usr/bin/cc (-O2 -std=c11 -Wall)   cxx = /usr/bin/c++ (-O2 -std=c++17 -Wall)
[结论] - 编译与运行功能就绪。
       - AI 功能未启用(api_key 为空);编辑、编译、运行均不受影响。
DOCTOR_EXIT=0
```

---

## B. 界面渲染

> 注意:以下运行的是 **`/tmp/cppide-poc/cppide`**(带 2 处源码补丁的验证产物),
> 因为仓库自身编译不出二进制。仓库源码全程未被修改。

### B1. 启动

```
$ osascript -e 'tell application "Terminal"
    activate
    set w to do script "cd /tmp/cppide-poc && ./cppide src/main.cpp"
    return "tty=" & (tty of w)
  end tell'
tty=/dev/ttys014
OSASCRIPT_EXIT=0
```

osascript **未被 TCC 拒绝**,Terminal 窗口正常打开。

(仓库根目录**没有** `main.cpp`,只有 `src/main.cpp`;因此用 `src/main.cpp` 作为打开对象,
这样能同时验证读文件、语法高亮、行号与中文宽字符渲染。)

### B2. 进程存活

```
$ ps -o pid=,etime=,tty=,command= -p <pid>       # T+4s
74793 00:09 ttys014  ./cppide src/main.cpp

$ ps -o pid=,etime=,tty=,command= -p 74793       # T+58s
74793 00:58 ttys014  ./cppide src/main.cpp
```

两次 **PID 一致(74793)**,elapsed 00:58,远超要求的 35 秒,进程稳定存活。

### B3. 截图 — 失败,如实记录

```
$ screencapture -x .../artifacts/cppide-ui.png
could not create image from display
rc=1

$ screencapture -x -R 60,60,600,400 /tmp/probe1.png
could not create image from rect
rc=1

$ screencapture -o -x /tmp/probe2.png
could not create image from display
rc=1
```

三种形式全部失败,**没有产出任何 png**。原因是当前进程未获得
macOS「屏幕录制 / Screen Recording」TCC 授权。间隔数分钟重试仍然失败。
**没有 `cppide-ui.png` / `cppide-ui-restart.png` 产出,不编造。**

### B4. 界面内容 — 用两条不依赖截图权限的通道取证

**通道一:AppleScript 读取真实 Terminal 窗口的回显内容**(即窗口里肉眼可见的字符):

```
$ osascript -e 'tell application "Terminal" ... return contents of selected tab ...'
 400     return 3;
 401   }
 402
 403   // 8) curl 全局初始化必须早于任何线程启动(AiService 的 worker 在 App 里起
 404   HttpChat::globalInit();
 ...
─[编译]─[运行]─[AI*]─[输入]─────────────────────────────────────────────────────
cppide 就绪 · 练习模式 · Ctrl-T 切模式 · Ctrl-B 编译 · Ctrl-R 运行 · F1 帮助
配置:未找到配置文件 /Users/hechenyu/.config/cppide/config.json:已使用默认设置,AI 功能已关闭。
...
 练习模式  │ main.cpp* │ 402:1 │ C++ │ AI 未配置                          F1帮助
```

**通道二:在受控 pty(100x30, TERM=xterm-256color, UTF-8)里跑,用 pyte 终端模拟器
忠实还原屏幕缓冲区**(pyte 装在 `/tmp/pylibs`,`pip3 install --target`,未污染系统):

```
child_still_running=True
   1 // main.cpp —— 进程入口
   2 //
   3 // 启动顺序(architecture.md §10,顺序不能错):
   4 //   setlocale(LC_ALL,"")            必须早于 initscr(否则中文宽度全按 1 算)
   5 //   signal(SIGPIPE, SIG_IGN)        libcurl 与 runProcess 都需要
   6 //   装 endwin 安全网                 atexit + std::set_terminate + 致命信号
   7 //   解析 argv
   8 //   ConfigLoader::load
   9 //   HttpChat::globalInit()          必须在任何线程启动之前
  10 //   构造 App(内部 Ui::init,再按需启动 AiService 线程)
  11 //   run()
  12 //   App 析构 -> AiService/Runner 析构(close + join,绝不 detach)-> Ui 析构
  13 //   Ui::emergencyShutdown()(幂等 endwin 兜底)
  14 //   HttpChat::globalCleanup()
  15 //
  16 // ★ 本文件不 include <curses.h>:归一化键码与 doctor 报告都由 ui.cpp 提供。
  17 // ★ --help / --version / --print-config / --doctor 是**纯 stdout、非交互**的,
  18 //   绝不初始化 ncurses —— 这是无 tty 环境里唯一能验证本程序的入口。
─[编译]─[运行]─[AI*]─[输入]────────────────────────────────────────────────────────────
cppide 就绪 · 练习模式 · Ctrl-T 切模式 · Ctrl-B 编译 · Ctrl-R 运行 · F1 帮助
配置:未找到配置文件 /Users/hechenyu/.config/cppide/config.json:已使用默认设置,AI 功能已关闭。
配置:可执行 `cppide --print-config > /Users/hechenyu/.config/cppide/config.json` 生成示例配置,再把
api_key 填进去。
配置:AI 未配置:请在 /Users/hechenyu/.config/cppide/config.json 里填写 api_key,或设置环境变量
CPPIDE_API_KEY。编辑、编译、运行功能均不受影响。
配置:未配置 model,请按 DeepSeek 官方文档填写模型名。在此之前 AI
功能显示为"未配置"且不会发出任何请求;编辑、语法高亮、编译、运行均不受影响。


 练习模式  │ main.cpp │ 1:1 │ 未找到配置文件 /Users/hechenyu/.config/cppide/config.json:已使… F1帮助
```

**能辨认出的 UI 元素**(不是白屏、不是黑屏、不是一屏报错):

* 左侧**行号栏**(`1`…`18`,右对齐)
* **编辑区**,载入了 `src/main.cpp` 的真实内容;中文注释宽度正确,`——`/`★`/`§`
  等宽字符与制表对齐没有错位 —— 说明 `-D_XOPEN_SOURCE_EXTENDED` 打开的宽字符
  渲染路径确实生效
* **面板标签栏** `─[编译]─[运行]─[AI*]─[输入]─────`,横线铺满整宽
* **消息/面板区**:就绪提示 + 4 条配置告警(自动换行正确)
* 底部**状态栏**:`练习模式 │ main.cpp │ 1:1 │ C++ │ AI 未配置 ... F1帮助`
  —— 含模式、文件名、行:列、语言、AI 状态、帮助提示
* 编辑过之后文件名变成 `main.cpp*`(脏标记),说明按键输入被正常处理

### B5. 端口

```
$ lsof -nP -iTCP -sTCP:LISTEN | grep -i cppide
(无输出,grep rc=1)

$ lsof -p 74793 | grep -iE "TCP|UDP"
(无输出)
```

**确认无任何监听端口,连 socket 都没有** —— 与「纯本地 TUI,不是服务」一致。

---

## C. 重跑验证

### C1. 停止

```
$ pkill -f "cppide src/main.cpp"
PKILL_EXIT=0
$ ps aux | grep -i "cppide src/main" | grep -v grep
(无输出,rc=1)
$ pgrep -f "cppide src/main.cpp"
(无输出,rc=1)
```

进程已确认消失。

### C2. 全新 shell 重启

重启命令的**精确文本**:

```
osascript -e 'tell application "Terminal" to do script "cd /tmp/cppide-poc && ./cppide src/main.cpp"'
```

```
tty=/dev/ttys016
RESTART_EXIT=0

$ ps -o pid=,etime=,tty=,command= -p <pid>
76413 00:11 ttys016  ./cppide src/main.cpp
```

新 PID **76413**,在全新 tty(ttys016)上。再次读取窗口内容,界面**重新完整渲染**:

```
   5 //   signal(SIGPIPE, SIG_IGN)        libcurl 与 runProcess 都需要
   ...
  12 //   App 析构 -> AiService/Runner 析构(close + join,绝不 detach)-> Ui 析构
─[编译]─[运行]─[AI*]─[输入]─────────────────────────────────────────────────────
cppide 就绪 · 练习模式 · Ctrl-T 切模式 · Ctrl-B 编译 · Ctrl-R 运行 · F1 帮助
...
 练习模式  │ main.cpp │ 1:1 │ C++ │ AI 未配置                             F1帮助
```

光标回到 `1:1`、文件名无脏标记,是干净的全新会话。**重启验证通过。**

---

## D. 收尾核对

### D1. `git status --porcelain` 完整输出

```
 M Makefile
 D cppide
 D cppide-debug
 D src/ai.d          D src/ai.dbg.d          D src/ai.dbg.o          D src/ai.o
 D src/aihttp.d      D src/aihttp.dbg.d      D src/aihttp.dbg.o      D src/aihttp.o
 D src/app.d         D src/app.dbg.d         D src/app.dbg.o         D src/app.o
 D src/build.d       D src/build.dbg.d       D src/build.dbg.o       D src/build.o
 D src/config.d      D src/config.dbg.d      D src/config.dbg.o      D src/config.o
 D src/editor.d      D src/editor.dbg.d      D src/editor.dbg.o      D src/editor.o
 D src/highlight.d   D src/highlight.dbg.d   D src/highlight.dbg.o   D src/highlight.o
 D src/json.d        D src/json.dbg.d        D src/json.dbg.o        D src/json.o
 D src/keys.d        D src/keys.dbg.d        D src/keys.dbg.o        D src/keys.o
 D src/main.d        D src/main.dbg.d        D src/main.dbg.o        D src/main.o
 D src/panel.d       D src/panel.dbg.d       D src/panel.dbg.o       D src/panel.o
 D src/proc.d        D src/proc.dbg.d        D src/proc.dbg.o        D src/proc.o
 D src/textbuf.d     D src/textbuf.dbg.d     D src/textbuf.dbg.o     D src/textbuf.o
 D src/ui.d          D src/ui.dbg.d          D src/ui.dbg.o          D src/ui.o
 D src/util.d        D src/util.dbg.d        D src/util.dbg.o        D src/util.o
```

合计:**62 个 D + 1 个 M**,无未跟踪文件(`--untracked-files=all` 无 `??` 条目)。

分类标注:

| 路径 | 分类 | 为什么变成这样 |
|---|---|---|
| `Makefile` | **构建配置**(唯一的人为改动) | 取消第 34 行注释,打开 `-D_XOPEN_SOURCE_EXTENDED`。macOS SDK 的 `curses.h` 默认 `NCURSES_WIDECHAR=0`,不打开这个宏就拿不到 `get_wch`/`add_wch`/`waddnwstr`/`cchar_t`,必然编译失败。 |
| `cppide`、`cppide-debug` | **构建产物**(2 个) | `make clean` 删除。它们是仓库里误提交的 **Linux ELF aarch64** 可执行文件,在 macOS 上既不能运行也不能参与链接,必须清掉。 |
| `src/*.o`、`src/*.dbg.o`(30 个) | **构建产物** | `make clean` 删除。同为误提交的 ELF aarch64 目标文件;且其 mtime 晚于对应 `.cpp`,不删的话 `make` 会跳过编译直接拿 ELF 去链接,必挂。 |
| `src/*.d`、`src/*.dbg.d`(30 个) | **构建产物** | `make clean` 删除。GCC 生成的依赖文件,内含 Linux 头文件路径,对 macOS 无效。 |

**源码 `src/*.cpp`、`src/*.h`、`tests/`、`README.md`、`config.sample.json` 全部零改动。**

如需完全还原(含恢复那些 Linux 产物):`git -C /Users/hechenyu/explore/test-ide/cppide checkout -- .`

### D2. shell 配置 mtime

```
$ stat -f "%Sm %N" -t "%Y-%m-%d %H:%M:%S" ~/.zshrc ~/.zprofile ~/.bash_profile ~/.profile
2026-09-02 22:10:46 /Users/hechenyu/.zshrc
2026-03-22 16:41:01 /Users/hechenyu/.zprofile
2025-11-15 22:09:46 /Users/hechenyu/.profile
```

(`~/.bash_profile` 不存在。)三个文件的 mtime **全部早于 2026-09-07 15:31:38 CST**,
未被触碰。全程未执行 `brew install` / `npm install -g` / `cargo install` / `sudo`,
未改 PATH、未改系统工具链。唯一一次安装是
`pip3 install --target /tmp/pylibs pyte`(带 `--target`,落在 `/tmp`,仅用于终端渲染取证)。

### D3. 工作台根目录

```
$ ls -a /Users/hechenyu/explore/test-ide
.  ..  .flower  cppide  runs
```

**除 `cppide/`、`.flower/`、`runs/` 外无新增条目。** 临时文件全部在 `/tmp`
(`/tmp/cppide-poc`、`/tmp/pylibs`、`/tmp/cppide-build.log`、`/tmp/render.txt`),
未写入工作台目录。`.flower/notes/` 与 `runs/` 未触碰。

---

## 待办 / 需要人来决定

仓库要能在 macOS 上构建,还差 **2 处源码改动(共 3 行)**,已定位到行,但按任务边界我没有动:

1. `src/proc.cpp:125` 与 `src/proc.cpp:217` — 去掉 `::sigemptyset(` 的 `::`
2. `src/ui.cpp` — 增加 `#include <unistd.h>`

两处都是纯可移植性修复,不改变任何行为,对 Linux 构建也无副作用
(`sigemptyset` 无 `::` 在 glibc 下照样解析到函数;`<unistd.h>` 本来就该被显式包含)。
`/tmp/cppide-poc` 是已验证可用的参考实现。
