# 01 — 侦察报告:cppide

> 本轮**只侦察**:未安装任何依赖、未构建、未启动、未修改任何 shell 配置或系统环境。
> 唯一的文件系统写入是 `git clone` 产生的 `/Users/hechenyu/explore/test-ide/cppide/`
> 以及本报告文件本身。

---

## 1. 基线环境快照(SESSION_START 前后)

### 1.1 SESSION_START

```
$ date '+%Y-%m-%d %H:%M:%S %Z'
2026-09-07 15:31:38 CST
```

### 1.2 uname

```
$ uname -a
Darwin Air 25.2.0 Darwin Kernel Version 25.2.0: Tue Nov 18 21:08:48 PST 2025; root:xnu-12377.61.12~1/RELEASE_ARM64_T8132 arm64
```

平台:macOS(Darwin 25.2.0),Apple Silicon(arm64 / T8132)。

### 1.3 工作目录初始内容

```
$ ls -a /Users/hechenyu/explore/test-ide
.
..
.flower
runs
```

clone 之前工作目录下**没有** `cppide/`(已确认 `NOT_EXISTS`,未做任何删除操作)。

### 1.4 Shell 配置文件 mtime(用于证明零改动)

```
$ ls -la ~/.zshrc ~/.zprofile ~/.bash_profile ~/.profile 2>/dev/null
-rw-r--r--@ 1 hechenyu  staff   21 Nov 15  2025 /Users/hechenyu/.profile
-rw-r--r--@ 1 hechenyu  staff  527 Mar 22 16:41 /Users/hechenyu/.zprofile
-rw-r--r--  1 hechenyu  staff  580 Sep  2 22:10 /Users/hechenyu/.zshrc
```

| 文件 | 存在 | size | mtime |
|---|---|---|---|
| `~/.profile` | 是 | 21 | Nov 15 2025 |
| `~/.zprofile` | 是 | 527 | Mar 22 16:41 |
| `~/.zshrc` | 是 | 580 | Sep 2 22:10 |
| `~/.bash_profile` | **不存在** | — | — |

(`ls` 退出码 1 即因 `~/.bash_profile` 不存在。)

### 1.5 工具可用性

```
$ which git node npm pnpm yarn python3 cmake clang make cargo go
git:     /usr/bin/git
node:    /Users/hechenyu/.nvm/versions/node/v24.11.0/bin/node
npm:     /Users/hechenyu/.nvm/versions/node/v24.11.0/bin/npm
pnpm:    /Users/hechenyu/.nvm/versions/node/v24.11.0/bin/pnpm
yarn:    /Users/hechenyu/.nvm/versions/node/v24.11.0/bin/yarn
python3: /Library/Frameworks/Python.framework/Versions/3.13/bin/python3
cmake:   /opt/homebrew/bin/cmake
clang:   /usr/bin/clang
make:    /usr/bin/make
cargo:   /Users/hechenyu/.cargo/bin/cargo
go:      N/A(go not found)
```

版本:

| 工具 | 版本 |
|---|---|
| git | git version 2.50.1 (Apple Git-155) |
| node | v24.11.0 |
| npm | 11.6.1 |
| pnpm | 10.31.0 |
| yarn | 1.22.22 |
| python3 | Python 3.13.7 |
| cmake | cmake version 4.3.2 |
| clang | Apple clang version 17.0.0 (clang-1700.4.4.1),Target: arm64-apple-darwin25.2.0 |
| make | GNU Make 3.81 |
| cargo | cargo 1.91.1 (ea2d97820 2025-10-10) |
| go | **N/A** |

### 1.6 本项目实际需要的工具链(额外探测)

```
$ xcode-select -p
/Applications/Xcode.app/Contents/Developer

$ xcrun --show-sdk-path
/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk

$ ls $SDK/usr/lib/ | grep -iE 'ncurses|curl'
libcurl.3.tbd
libcurl.4.tbd
libcurl.tbd
libncurses.5.4.tbd
libncurses.5.tbd
libncurses.tbd

$ ls $SDK/usr/include/curl/curl.h
/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/curl/curl.h

$ brew list ncurses
brew ncurses: NOT INSTALLED

$ brew --prefix ncurses
stdout='/opt/homebrew/opt/ncurses' rc=0     # ← 注意:目录并不存在,但退出码是 0
$ ls -d /opt/homebrew/opt/ncurses
DOES NOT EXIST
```

结论:项目所需的 `clang++` / 系统 `ncurses`(SDK stub + `curses.h`)/ 系统 `libcurl`
(SDK stub + `curl/curl.h`)**本机全部具备**,无需安装任何东西。
但 `brew --prefix ncurses` 会返回一个**不存在**的路径且退出码为 0 —— 见 §5 风险 R3。

---

## 2. Clone 与验证

### 2.1 clone

```
$ git clone https://github.com/ChenyuHeee/cppide /Users/hechenyu/explore/test-ide/cppide
Cloning into '/Users/hechenyu/explore/test-ide/cppide'...
```

完整 clone(未加 `--depth`),默认分支。目录此前不存在,无覆盖 / 无删除。

### 2.2 验证

```
$ git -C cppide remote get-url origin
https://github.com/ChenyuHeee/cppide

$ git -C cppide rev-parse --is-shallow-repository
false

$ git -C cppide rev-parse HEAD
d23d6367c02b4153c9f7d661f333dbd83153e8fe

$ git ls-remote https://github.com/ChenyuHeee/cppide HEAD
d23d6367c02b4153c9f7d661f333dbd83153e8fe	HEAD

$ git -C cppide branch --show-current
main

$ git -C cppide status --porcelain
(空)

$ git -C cppide log -1 --format='%h %ad %an %s' --date=iso
d23d636 2026-09-07 10:50:32 +0800 Chenyu He 补齐完整记录:transcript、编译产物、工具输出转储

$ git -C cppide rev-list --count HEAD
2
```

| 检查项 | 结果 |
|---|---|
| origin URL | `https://github.com/ChenyuHeee/cppide` ✅ |
| non-shallow | `false` ✅ |
| 本地 HEAD | `d23d6367c02b4153c9f7d661f333dbd83153e8fe` |
| 远端 HEAD | `d23d6367c02b4153c9f7d661f333dbd83153e8fe` |
| 本地 == 远端 | ✅ 一致 |
| 默认分支 | `main` |
| working tree | ✅ 干净(`status --porcelain` 为空) |
| 提交总数 | 2 |

> 备注:首次 `git ls-remote` 遇到一次瞬时 TLS 故障
> (`LibreSSL SSL_connect: SSL_ERROR_SYSCALL in connection to github.com:443`),
> 重试第 1 次即成功。非仓库问题,记录在案。
>
> 对远端**未做任何写操作**(无 push、无 PR、无 tag)。

---

## 3. 文件树

### 3.1 根目录

```
$ ls -la /Users/hechenyu/explore/test-ide/cppide
total 28840
drwxr-xr-x  13 hechenyu  staff       416 Sep  7 15:32 .
drwxr-xr-x   5 hechenyu  staff       160 Sep  7 15:31 ..
drwxr-xr-x   7 hechenyu  staff       224 Sep  7 15:32 .flower
drwxr-xr-x  12 hechenyu  staff       384 Sep  7 15:32 .git
-rw-r--r--   1 hechenyu  staff       290 Sep  7 15:32 .gitignore
-rw-r--r--   1 hechenyu  staff      3860 Sep  7 15:32 Makefile
-rw-r--r--   1 hechenyu  staff     44259 Sep  7 15:32 README.md
-rw-r--r--   1 hechenyu  staff      2528 Sep  7 15:32 config.sample.json
-rwxr-xr-x   1 hechenyu  staff    605624 Sep  7 15:32 cppide          ← 提交进仓库的二进制
-rwxr-xr-x   1 hechenyu  staff  14099448 Sep  7 15:32 cppide-debug    ← 提交进仓库的二进制
drwxr-xr-x   4 hechenyu  staff       128 Sep  7 15:32 runs
drwxr-xr-x  92 hechenyu  staff      2944 Sep  7 15:32 src
drwxr-xr-x  18 hechenyu  staff       576 Sep  7 15:32 tests
```

仓库总大小 72M,tracked 文件 303 个。

### 3.2 一级子目录(`find . -maxdepth 2 -not -path './.git/*'`)

```
./.flower
./.flower/INDEX.md
./.flower/artifacts        (23 个 .md:wave1~wave5 各阶段报告、architecture.md、验收审计.md 等)
./.flower/notes            (需求.md 技术决策.md 跨模块约定.md 交付说明.md 问答记录.md)
./.flower/scripts          (probe-toolchain.sh、wave*-verify.sh、pty 脚本等 13 个)
./.flower/spill
./.gitignore
./Makefile
./README.md
./config.sample.json
./cppide
./cppide-debug
./runs
./runs/manifest.json       (8218 B,每一步的 session_id / cost_usd / num_turns / text)
./runs/sessions.db         (20303872 B ≈ 19.4 MB,原始 transcript)
./src                      (15 个 .h + 15 个 .cpp + 编译产物 .o/.dbg.o/.d/.dbg.d,共 92 项)
./tests                    (16 个 test_*.cpp)
```

`src/` 源文件(15 组):`ai` `aihttp` `app` `build` `config` `editor` `highlight` `json`
`keys` `main` `panel` `proc` `textbuf` `ui` `util`(另有 header-only 的 `mailbox.h`)。

`tests/`:`test_ai` `test_aihttp` `test_appai` `test_config` `test_diag` `test_editor`
`test_highlight` `test_json` `test_keys` `test_openpath` `test_panel` `test_proc`
`test_sse` `test_textbuf` `test_ui` `test_util`(16 个)。

### 3.3 `.gitignore` 全文

```
# 这是一份 human test 的**完整记录**仓库,不是发行版 —— 编译产物、二进制、
# 原始 transcript、工具输出转储都要留着,它们是这次运行的一部分。
# 唯一排除:填了真实 API key 的配置文件(只提交 config.sample.json)。
config.json
```

> 关键背景:**这个仓库刻意把编译产物和二进制一起提交了**,它是一份"完整记录"仓库
> 而非发行版。这直接导致了 §5 的 R1 风险。

---

## 4. 构建 / 依赖清单

### 4.1 清单扫描结果

| 清单 | 是否存在 |
|---|---|
| `package.json` / lockfile(npm / pnpm / yarn) | ❌ 无 |
| `CMakeLists.txt` | ❌ 无 |
| `requirements.txt` / `pyproject.toml` | ❌ 无 |
| `Cargo.toml` | ❌ 无 |
| `go.mod` | ❌ 无 |
| `Dockerfile` / `docker-compose.yml` | ❌ 无 |
| `meson.build` / `configure` / `configure.ac` / `SConstruct` | ❌ 无 |
| **`Makefile`** | ✅ **唯一的构建系统** |
| `config.sample.json` | ✅(运行期配置模板,非构建清单) |
| `runs/manifest.json` | ✅(记录文件,非构建清单) |

**唯一构建入口是根目录的 `Makefile`,手写 GNU make,无生成器、无包管理器。**

### 4.2 `Makefile` 全文

```make
# cppide —— C/C++ 终端 IDE(ncurses + libcurl,C++17)
#
# 依赖:ncurses(宽字符版)+ libcurl。
#   macOS  : 系统自带(brew 的 ncurses 若存在则优先)
#   Debian : apt-get install build-essential libncursesw5-dev libcurl4-openssl-dev
#            (trixie 上包名为 libncurses-dev + libcurl4-gnutls-dev 亦可)
#
# 常用目标:
#   make                 编译出 ./cppide
#   make check-headers   Wave 1 验收门:每个头文件必须自给自足
#   make tests           编译并运行 tests/test_*.cpp
#   make debug           -O0 -g + ASan/UBSan,产物是 ./cppide-debug(与 release 互不干扰)

BIN      ?= cppide
CXX      ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter -MMD -MP
PREFIX   ?= /usr/local
UNAME_S  := $(shell uname -s)

# tests/*.cpp 直接写 #include "config.h"(不带 ../src/),所以搜索路径必须带 -Isrc。
# 放在 CPPFLAGS 而不是 CXXFLAGS:check-headers 的 SYNFLAGS 会过滤 CXXFLAGS,
# 而 CPPFLAGS 三个目标(%.o / check-headers / tests)都会用到。
CPPFLAGS += -Isrc

ifeq ($(UNAME_S),Darwin)
  NCURSES_PREFIX := $(shell brew --prefix ncurses 2>/dev/null)
  ifneq ($(NCURSES_PREFIX),)
    CPPFLAGS += -I$(NCURSES_PREFIX)/include
    LDFLAGS  += -L$(NCURSES_PREFIX)/lib
  endif
  LDLIBS += -lncurses -lcurl -lpthread
  # 若 macOS 自带的 ncurses 头不肯给出宽字符原型(get_wch / add_wch / cchar_t 未声明),
  # 打开下面这行;Debian 的 ncursesw 头默认已 NCURSES_WIDECHAR=1,不需要它。
  # CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
else
  # Linux:宽字符符号(add_wch/get_wch)只在 ncursesw 里,必须链 -lncursesw
  LDLIBS += -lncursesw -lcurl -lpthread
endif

SRC := $(wildcard src/*.cpp)
OBJ := $(SRC:.cpp=.o)
DEP := $(OBJ:.o=.d)
HDR := $(wildcard src/*.h)

# debug(ASan/UBSan)走**完全独立**的产物名:目标文件 src/*.dbg.o、可执行 cppide-debug。
# 为什么不是老写法 `debug: clean all`:clean 与 all 是两个平级先决条件,`make debug -j4`
# 下 GNU make 会并发跑它们,clean 把已经编出的 .o 删掉,链接阶段报
# "cannot find src/ai.o";而且它会连 ./cppide 一起删,把正在跑的验收脚本打挂。
# 现在 debug 与 release 共存,可并行、互不删对方产物。
DBGBIN   := $(BIN)-debug
DBGOBJ   := $(SRC:.cpp=.dbg.o)
DBGDEP   := $(DBGOBJ:.o=.d)
SANFLAGS := -fsanitize=address,undefined
DBGCXXFLAGS := $(filter-out -O2,$(CXXFLAGS)) -O0 -g $(SANFLAGS)

# 语法检查时不要生成 .d(会与 .o 的依赖文件同名互相覆盖)
SYNFLAGS := $(filter-out -MMD -MP,$(CXXFLAGS))

all: $(BIN)

$(BIN): $(OBJ)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)

%.o: %.cpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c -o $@ $<

# Wave 1 的验收门:每个头文件必须自给自足。
# 用"生成一个只 include 该头的 TU"而不是直接 -x c++ 头文件本身:
# 后者会让 GCC 无条件报 "#pragma once in main file"(该警告无法用 -Wno-* 关掉),
# 而且"被 include"才是头文件真实的使用方式。
check-headers:
	@for h in $(HDR); do echo "  $$h"; \
	  printf '#include "%s"\n' "$$h" | \
	  $(CXX) $(CPPFLAGS) $(SYNFLAGS) -fsyntax-only -x c++ - || exit 1; done
	@echo "check-headers: OK ($(words $(HDR)) 个头文件)"

debug: $(DBGBIN)

$(DBGBIN): $(DBGOBJ)
	$(CXX) $(LDFLAGS) $(SANFLAGS) -o $@ $^ $(LDLIBS)

src/%.dbg.o: src/%.cpp
	$(CXX) $(CPPFLAGS) $(DBGCXXFLAGS) -c -o $@ $<

tests: $(filter-out src/main.o,$(OBJ))
	@for t in tests/test_*.cpp; do \
	  $(CXX) $(CPPFLAGS) $(CXXFLAGS) -o /tmp/$$(basename $$t .cpp) $$t \
	    $(filter-out src/main.o,$(OBJ)) $(LDLIBS) && /tmp/$$(basename $$t .cpp) || exit 1; done

install: $(BIN)
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 0755 $(BIN) $(DESTDIR)$(PREFIX)/bin/$(BIN)

clean:
	rm -f $(OBJ) $(DEP) $(BIN) $(DBGOBJ) $(DBGDEP) $(DBGBIN)

-include $(DEP)
-include $(DBGDEP)
.PHONY: all clean debug tests install check-headers
```

### 4.3 make 目标一览

| 命令 | 作用 |
|---|---|
| `make` | 编译出 `./cppide`(15 个 `.cpp` → 15 个 `.o` → 链接) |
| `make tests` | 编译并逐个运行 `tests/test_*.cpp`,任一失败即停(产物落在 `/tmp/`) |
| `make check-headers` | 验收门:对每个 `src/*.h` 生成一个只 `#include` 它的 TU 做 `-fsyntax-only`(15 个头) |
| `make debug` | `-O0 -g -fsanitize=address,undefined` 编出独立的 `./cppide-debug`(目标文件 `src/*.dbg.o`),不依赖 `clean`,`-j4` 安全 |
| `make clean` | 删掉 `.o` / `.d` / `cppide` 与 debug 的 `*.dbg.o` / `cppide-debug` |
| `make install` | `install -m 0755 cppide $(PREFIX)/bin/`,`PREFIX` 默认 `/usr/local`(需 sudo,**本轮不执行**) |

### 4.4 `config.sample.json` 全文(运行期配置模板)

```json
{
  "_comment": "cppide 配置文件。以 _ 开头的键是注释,加载时会被忽略。所有字段都可省略,省略即用内置默认值。",
  "_comment_env": "环境变量优先级高于本文件:CPPIDE_API_KEY(或 DEEPSEEK_API_KEY)、CPPIDE_MODEL、CPPIDE_BASE_URL。配置文件路径可用 --config 或 CPPIDE_CONFIG 指定。",
  "_comment_api_key": "把 DeepSeek 控制台申请到的 key 填在这里。留空则 AI 功能关闭,编辑/编译/运行照常可用。切勿把填好 key 的本文件提交到版本库。",
  "api_key": "",
  "_comment_model": "模型 ID:留空则 AI 功能显示\"未配置\"且不发任何请求(编辑/编译/运行照常)。请按 DeepSeek 官方文档填写模型名 —— 本程序不内置任何模型名,也不对模型能力做假设。",
  "model": "",
  "base_url": "https://api.deepseek.com",
  "chat_path": "/v1/chat/completions",
  "stream": true,
  "_comment_ghost": "写代码模式的行内补全:停顿 ghost_delay_ms 毫秒后自动请求,两次请求至少间隔 ghost_min_interval_ms 毫秒(省钱),最多显示 ghost_max_lines 行。同一次停顿只会自动请求一次 —— 手离开键盘不动不会持续计费,要再来一次就再打字/移动光标,或按 Ctrl-A 手动请求。",
  "ghost_delay_ms": 500,
  "ghost_min_interval_ms": 1200,
  "ghost_max_lines": 8,
  "ai_connect_timeout_ms": 5000,
  "ai_timeout_ms": 20000,
  "ai_max_context_lines": 400,
  "max_tokens_code": 256,
  "max_tokens_practice": 512,
  "temperature_code": 0.2,
  "temperature_practice": 0.7,
  "_comment_prompt": "留空则使用内置提示词。练习模式的"不要输出可运行代码"后缀由程序强制追加,无法被覆盖。",
  "prompt_code": "",
  "prompt_practice": "",
  "_comment_build": "编译命令与参数。cflags 用于 .c,cxxflags 用于 .cc/.cpp/.cxx。写成 [] 表示不加任何参数。",
  "cc": "cc",
  "cxx": "c++",
  "cflags": ["-O2", "-std=c11", "-Wall"],
  "cxxflags": ["-O2", "-std=c++17", "-Wall"],
  "compile_timeout_ms": 30000,
  "_comment_run": "run_output_limit 是单次运行捕获的输出字节上限;stdin_file 留空则用【输入】面板里编辑的内容。",
  "run_timeout_ms": 5000,
  "run_output_limit": 1048576,
  "stdin_file": "",
  "_comment_editor": "tick_ms 是主循环的空转周期(毫秒),影响 ghost 触发与状态刷新的精度。",
  "tab_width": 4,
  "expand_tab": true,
  "auto_indent": true,
  "show_line_numbers": true,
  "panel_height": 10,
  "tick_ms": 60
}
```

(共 31 个可配字段;以 `_` 开头的键是注释,加载时忽略。)

---

## 5. 项目形态判定

### 5.1 结论

**原生终端 TUI 应用(ncurses),不是 Electron / 不是 Web / 不是 GUI / 不是 VS Code 扩展。**

一个从零实现的、跑在终端里的 **C/C++ 单文件代码编辑器**:自带语法高亮、一键编译运行、
以及基于 DeepSeek API 的 AI 辅助(「练习模式」只给中文思路,「写代码模式」给灰色 ghost 补全)。
为 ICPC / 算法竞赛训练场景做的,不依赖 vim / neovim / VSCode。

- **语言**:C++17
- **UI 框架**:ncurses(宽字符版,`curses.h` 只允许出现在 `src/ui.cpp`)
- **网络**:libcurl(`src/aihttp.cpp`,SSE 流式解析)
- **并发**:pthread + header-only `Mailbox<T>` 线程安全队列
- **JSON**:自研极简 `mj::Value`(`src/json.cpp`),无第三方库
- **第三方依赖**:**零**。只依赖 ncurses + libcurl 这两个系统库。

### 5.2 端口

**无。** 这不是 Web 形态,不 listen、不 bind、不开任何端口。
唯一的网络行为是作为 **HTTPS 客户端**出站访问 `https://api.deepseek.com`
(可配置 `base_url` / `chat_path`),且 `api_key` 留空时 worker 线程**根本不创建**、
一个请求都不会发。

已扫描 `src/*.cpp` / `src/*.h`,无 `listen(` / `bind(` / 硬编码端口号。

### 5.3 README 声明的边界(原文要点)

- **只服务 C / C++**,只接受 C/C++ 扩展名,其它类型启动时就被拒绝。
  `.c` = C;`.C` `.cpp` `.cc` `.cxx` `.c++` `.h` `.hpp` `.hh` `.hxx` `.h++` `.hp` = C++。
  除 `.c`/`.C` 这一对外,扩展名大小写不敏感。
- **只面向 macOS 终端**(Terminal.app / iTerm2)。不做 GUI、不做网页版、不做 Windows 适配。
  Linux 上能编能跑(开发就是在 Linux 容器里做的),但不是交付目标。
- **只编译当前打开的那一个文件**。没有工程、没有 CMake / Makefile 驱动、没有多文件链接。
- 没有 LSP、没有跨文件索引、没有重构、没有调试器集成、没有 Git 集成。
- 不做 OJ 对接、不做自动提交、不做题库。
- 不代买 / 不代配 API key。

### 5.4 模块职责(README §8)

| 文件 | 职责 |
|---|---|
| `src/main.cpp` | 进程入口:`setlocale` / 忽略 SIGPIPE / curl 全局初始化 / `endwin` 崩溃安全网 / 解析 argv / `--help` `--version` `--print-config` `--doctor` |
| `src/app.{h,cpp}` | `AppModel` + `App`:主循环、按键分派、事件排空、编译/运行/AI 编排 |
| `src/ui.{h,cpp}` | ncurses 初始化与全部绘制。**`curses.h` 只允许出现在这里** |
| `src/editor.{h,cpp}` | 光标、视口、编辑操作、行剪贴板、查找、Ghost 状态与唯一的 `acceptGhost()` |
| `src/textbuf.{h,cpp}` | 行数组 + 逆操作日志撤销、文件读写、语言判定 |
| `src/highlight.{h,cpp}` | `Highlighter`(纯函数,单行扫描)+ `HighlightCache` |
| `src/panel.{h,cpp}` | 输出面板(行/未读标记/错误数/滚动)+ `StdinBuffer` |
| `src/proc.{h,cpp}` | `runProcess`(fork+exec+poll,超时/输出上限/进程组)+ `Runner` 后台作业线程 |
| `src/build.{h,cpp}` | `Diag` / `Builder`:编译命令装配、诊断解析、临时二进制路径、`binaryStale` |
| `src/ai.{h,cpp}` | `AiMode` / `AiSink` / `AiRequest` / `AiService`:worker 线程、prompt 组装、上下文截断、generation 取消、代码围栏剥离 |
| `src/aihttp.{h,cpp}` | `HttpChat`(libcurl)+ `SseParser` + 中文错误映射。**适配非 OpenAI 兼容 API 只需改这一个文件** |
| `src/config.{h,cpp}` | `Config` + `ConfigLoader`:路径推导、加载、clamp、降级、`sampleJson()` |
| `src/json.{h,cpp}` | `mj::Value` 极简 JSON,链式下标对缺失/越界/类型不符返回 Null 而不抛 |
| `src/keys.{h,cpp}` | `Action` 枚举 + 全局绑定表 + `Ctrl()`/`Alt()` + 帮助浮层文本 |
| `src/mailbox.h` | `Mailbox<T>` 线程安全队列(header-only),UI 线程与 worker 线程之间的唯一通道 |
| `src/util.{h,cpp}` | 字符串 / 路径 / 文件 / 时间 / UTF-8 / 显示宽度(`wcwidth`) |

---

## 6. 装依赖 / 构建 / 启动

### 6.1 装依赖

**macOS(交付目标平台)—— 依赖全部是系统自带的:**

```sh
xcode-select --install        # 如果还没装过 Command Line Tools
```

本机已确认 `xcode-select -p` = `/Applications/Xcode.app/Contents/Developer`,
SDK 里 `libncurses.tbd` / `libcurl.tbd` / `curl/curl.h` / `curses.h` 齐全,
**无需执行任何安装命令**。

README 说"brew 的 ncurses 若存在则优先",但**不是必需**;本机未装 brew ncurses。

**Linux(仅作参考,非本机路径):**

```sh
sudo apt-get install build-essential libncursesw5-dev libcurl4-openssl-dev
# Debian trixie 上包名亦可写作 libncurses-dev + libcurl4-gnutls-dev
```

### 6.2 构建

README §1.1 给的标准流程:

```sh
cd /path/to/cppide
make                          # 产物:./cppide
./cppide --doctor             # 先自查一遍环境
./cppide main.cpp             # 开始用
```

**但在本机必须先清理 clone 带进来的 Linux 编译产物**(见 §7 R1):

```sh
cd /Users/hechenyu/explore/test-ide/cppide
make clean                    # 或:rm -f src/*.o src/*.d
make
```

其它可选目标:

```sh
make check-headers            # 15 个头文件自给自足验收门
make tests                    # 编译并逐个跑 16 个单元测试
make debug                    # ASan/UBSan 版 ./cppide-debug
```

### 6.3 启动

```sh
./cppide                      # 打开一个未命名空缓冲区
./cppide main.cpp             # 打开指定文件(一次只能开一个)
./cppide --doctor             # 非交互自查环境后退出
./cppide --help               # 用法 + 配置文件位置 + 整份快捷键表
./cppide --version            # cppide 0.1.0
./cppide --print-config       # 输出示例配置到 stdout
./cppide --config <PATH> ...  # 指定配置文件
```

**端口:无(非 Web 形态)。**

启动前的硬性检查(任一不过 → 中文报错 + **退出码 2**):给了两个及以上文件 /
扩展名不是 C/C++ / 路径是目录 / 新文件父目录不存在 / 不是普通文件 / 存在但读不了 / 未知选项。

**不在交互式终端里跑**(stdin 或 stdout 不是 tty,例如被重定向 / 在 CI 里)会报
「当前环境不是交互式终端…」并以**退出码 3** 退出。
`--help` / `--version` / `--print-config` / `--doctor` 四个非交互命令不受此限制。

> 这一条对自动化验收很关键:想在脚本里跑 TUI 必须用 **pty**(仓库 `.flower/scripts/`
> 里就有 `wave4-pty-loop.txt` / `wave4-pty-edit.txt` 这类 pty 驱动脚本)。

### 6.4 配置(可选,AI 功能才需要)

路径优先级(高→低):
1. 命令行 `--config <PATH>`
2. 环境变量 `CPPIDE_CONFIG`
3. `$XDG_CONFIG_HOME/cppide/config.json`
4. `~/.config/cppide/config.json` ← **推荐**

```sh
mkdir -p ~/.config/cppide
./cppide --print-config > ~/.config/cppide/config.json
$EDITOR ~/.config/cppide/config.json      # 把 api_key 填进去
```

环境变量覆盖(优先级:内置默认 < 配置文件 < 环境变量):

| 环境变量 | 覆盖谁 |
|---|---|
| `CPPIDE_API_KEY` | `api_key` |
| `DEEPSEEK_API_KEY` | `api_key`(`CPPIDE_API_KEY` 优先) |
| `CPPIDE_MODEL` | `model` |
| `CPPIDE_BASE_URL` | `base_url` |
| `CPPIDE_CONFIG` | 配置文件路径(被 `--config` 压过) |

**不配 key / 不配 model 也完全能用**:编辑、高亮、撤销重做、查找、跳行、编译、运行
全部照常;只是状态栏显示 `AI 未配置`,worker 线程根本不创建,一个请求都不发。
**降级契约**:配置文件不存在 / JSON 语法错 / 字段类型错 / 值越界 / 未知键
—— 一律降级为默认值 + 中文 warning,**绝不崩溃、绝不拒绝启动**。

### 6.5 编辑器内的编译 / 运行快捷键(README §4.3)

| 键 | 别名 | 动作 |
|---|---|---|
| `Ctrl-O` | `F2` | 保存 |
| `Ctrl-X` | `F10` | 退出(有未保存修改会先问 y/n/s,默认不退出) |
| `Ctrl-B` | `F5` | 编译当前文件(脏缓冲区先自动保存) |
| `Ctrl-R` | `F6` | 运行(必要时先自动编译) |
| `Ctrl-E` | `F7` | 编译并运行 |
| `Ctrl-N` / `Ctrl-P` | — | 下/上一个编译诊断 |
| `Ctrl-T` | `F8` | 切换 AI 模式(练习 ⇄ 写代码) |
| `Ctrl-A` | `F4` | 立即请求 AI |
| `Tab` / `Esc` | — | 接受 / 丢弃 ghost |

`F4` / `F5` 别名是给 tmux 用户的(tmux prefix 常占用 `Ctrl-B` / `Ctrl-A`)。

---

## 7. macOS 兼容性风险点

> README §10 已自陈:**「macOS 上未经真机验证。」全部自动化验证都在 Debian aarch64 容器里完成。**
> 以下 R1–R5 是本轮在**本机实地探测**后的结论,不是转述。

### R1 — 【阻断级,已实测确认】clone 带进来的 Linux ELF 产物会让 `make` 直接跳过编译去链接

仓库刻意提交了编译产物(见 `.gitignore` 注释:"编译产物、二进制…都要留着")。
这些产物是 **Linux ELF aarch64**:

```
$ file cppide
cppide: ELF 64-bit LSB pie executable, ARM aarch64, version 1 (GNU/Linux),
        dynamically linked, interpreter /lib/ld-linux-aarch64.so.1, for GNU/Linux 3.7.0

$ file cppide-debug
cppide-debug: ELF 64-bit LSB pie executable, ARM aarch64, version 1 (GNU/Linux), with debug_info

$ file src/ai.o src/ai.dbg.o
src/ai.o:     ELF 64-bit LSB relocatable, ARM aarch64, version 1 (SYSV)
src/ai.dbg.o: ELF 64-bit LSB relocatable, ARM aarch64, version 1 (SYSV), with debug_info
```

更要命的是 **`git clone` 后 15 个 `.o` 的 mtime 全部晚于对应的 `.cpp`**
(checkout 按字母序写盘,`ai.cpp` 先于 `ai.o`):

```
1788766324.376029367 src/ai.cpp
1788766324.378640289 src/ai.o      ← .o 更新
1788766324.411311444 src/ui.cpp
1788766324.414451325 src/ui.o      ← .o 更新
1788766324.330280184 cppide        ← 反而比 .o 更旧

统计:cpp 比 o 新(会触发重编)= 0
      o >= cpp(重编被跳过)     = 15   ← 全部 15 个
```

后果:`make` 认为 15 个 `.o` 全部 up-to-date → **一个文件都不编译** →
但 `cppide` 比 `.o` 旧,所以**链接步骤会执行** → Apple clang 拿到 15 个 Linux ELF `.o`
→ 链接失败。

**修法(必须在第一次 `make` 之前做)**:
```sh
make clean && make
# 或(保留仓库里那两个 Linux 二进制作为"记录"):
rm -f src/*.o src/*.d && make
```
注意 `make clean` 会连 `cppide` / `cppide-debug` 一起删掉,这会让 `git status` 变脏
(相对于那份"完整记录"提交)。若要保持记录完整,用上面第二条 `rm` 的写法。

### R2 — 【阻断级,已实测确认】macOS 的 `curses.h` 默认不给宽字符原型,必须打开 `-D_XOPEN_SOURCE_EXTENDED`

README §9 把这一条列为"候选原因",本轮已在本机 SDK 头文件里**确认它一定会发生**:

```
$SDK/usr/include/curses.h:173-179
  #ifndef NCURSES_WIDECHAR
  #if defined(_XOPEN_SOURCE_EXTENDED) || (defined(_XOPEN_SOURCE) && (_XOPEN_SOURCE - 0 >= 500))
  #define NCURSES_WIDECHAR 1
  #else
  #define NCURSES_WIDECHAR 0     ← macOS 默认走这里
  #endif

$SDK/usr/include/curses.h:1757-1759
  #if NCURSES_WIDECHAR
  /* Declarations from curses.wide */
  extern NCURSES_EXPORT(int) add_wch (const cchar_t *) ...
```

即 `add_wch` / `get_wch` / `cchar_t` 全部被 `#if NCURSES_WIDECHAR` 挡住,
而 macOS 上该宏默认为 **0**。同时已确认:

- `Makefile` 里那行是**注释掉的**:`# CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED`
- `src/` 下**没有任何文件**自己 `#define _XOPEN_SOURCE_EXTENDED` 或 `NCURSES_WIDECHAR`
  (`grep -rn '_XOPEN_SOURCE\|NCURSES_WIDECHAR' src/` 无命中)

**结论:本机 `make` 必然报 `use of undeclared identifier 'get_wch'` 之类的错。**

**修法**:把 `Makefile` 第 34 行的 `#` 去掉:
```make
  CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
```

### R3 — 【噪音级,已实测确认】`brew --prefix ncurses` 对未安装的 formula 也返回路径且 rc=0

```
$ brew list ncurses  → NOT INSTALLED
$ ls -d /opt/homebrew/opt/ncurses  → DOES NOT EXIST
$ brew --prefix ncurses  → stdout='/opt/homebrew/opt/ncurses'  rc=0
```

`Makefile` 的 Darwin 分支只判断 `$(shell brew --prefix ncurses)` 是否**非空**,
不判断目录是否存在,因此会加上指向**不存在目录**的
`-I/opt/homebrew/opt/ncurses/include` 和 `-L/opt/homebrew/opt/ncurses/lib`。

clang 对不存在的 `-I` / `-L` 只发 warning 不报错,会回落到 SDK 的系统 ncurses,
所以**不阻断构建**,但会产生噪音警告。若要干净,可 `make NCURSES_PREFIX=` 覆盖
(注意它是 `:=` 立即赋值,命令行覆盖有效)。

### R4 — 【已排除】`KEY_S*` 键码 static_assert 在本机**不会**炸

README §9 把这个列为第二个候选风险。本轮已逐个比对,**三个值完全一致,风险不存在**:

| 常量 | `src/keys.cpp` 硬编码 | macOS SDK `curses.h` | 一致? |
|---|---|---|---|
| `kNcBTab` / `KEY_BTAB` | 353(0541) | `#define KEY_BTAB 0541` = 353 | ✅ |
| `kNcSEnd` / `KEY_SEND` | 386(0602) | `#define KEY_SEND 0602` = 386 | ✅ |
| `kNcSHome` / `KEY_SHOME` | 391(0607) | `#define KEY_SHOME 0607` = 391 | ✅ |

`make tests` 里的 `static_assert` 应当直接通过。

### R5 — 【运行期,未验证】终端环境相关(locale / TERM / Option 键 / F 键)

README §9 列出、本轮**未实地验证**的运行期风险:

- **locale**:`--doctor` 里 `MB_CUR_MAX` 若为 1 说明 locale 不是 UTF-8,中文会乱码。
  程序在 `initscr()` 前 `setlocale(LC_ALL, "")`,只能沿用环境 locale。
  修法:`export LANG=zh_CN.UTF-8`(或 `en_US.UTF-8`)。
- **TERM**:方向键打出 `[A` `[B` 说明 `TERM` 不对,应为 `xterm-256color` / `screen-256color`。
- **Alt / Option**:`Alt-*` 组合依赖终端把 Option 发成 **Esc 前缀**。
  macOS 终端若把 Option 配成 CSI 修饰符(`ESC[1;3D`)或"输入特殊字符",按词移动会失效。
  替代:两步法(先按 `Esc` 松开,再按目标键)。
- **F 键**:macOS 上 `F5` / `F8` 默认被亮度/音量媒体键占用,需勾选"用作标准功能键"或按住 `fn`。
- **Backspace**:若终端把 Backspace 配成发送 Control-H 会完全失灵
  —— cppide **刻意不绑 `Ctrl-H`**,需把终端改回发送 `Delete`(`0x7F`)。
- **tmux**:`Ctrl-B`(编译)/ `Ctrl-A`(问 AI)常被 tmux prefix 吃掉,改用 `F5` / `F4`。
- **最小可用尺寸 60x16**,更小的窗口只画一行中文提示。
- **`$TMPDIR` 形态**:README 自陈的第三个 macOS 平台风险。
  `src/util.cpp:433` 读 `$TMPDIR`,取不到则回落 `/tmp`;macOS 的 `$TMPDIR` 是
  `/var/folders/…` 这种长路径,与 Linux 的 `/tmp` 形态不同。编译产物落在
  `$TMPDIR/cppide-<hash>-<stem>`(`src/build.h:59`)。
- **clang 诊断格式**:README 自陈的第四个平台风险 —— 诊断解析(`src/build.cpp`)
  是按 gcc/clang 输出格式写的,Apple clang 的格式差异可能影响"编译错误跳行"。

### 补充:其它已知限制(README §10 摘录)

- **不做打包分发**:没有 brew formula、没有签名、没有安装器。`make install` 就是 `cp`。
- **Windows 完全没做。**
- 面板区显示哪个标签跟着焦点走,没有"固定盯着某个面板"的选项。
- 状态栏挤不下时按优先级丢字段;`F1帮助` 固定右对齐、永不被挤掉。

---

## 8. 安全性(README §11 + 实地核对)

- **代码里没有任何硬编码的 API key**,`config.sample.json` 里 `api_key` 是空串。
- `.gitignore` 只排除 `config.json`(填了真实 key 的那份),`config.sample.json` 可安全提交。
- `--doctor` 只显示「已配置(已隐去)」,绝不回显 key 本身;AI 错误文案里也不带 key。
- 唯一出站网络目标是 `base_url`(默认 `https://api.deepseek.com`),
  且 `api_key` 为空时 worker 线程根本不创建、零请求。

---

## 9. 仓库自带的记录文件(非代码,供后续参考)

| 路径 | 内容 |
|---|---|
| `cppide/.flower/INDEX.md` | 索引 |
| `cppide/.flower/notes/` | `需求.md` `技术决策.md` `跨模块约定.md` `交付说明.md` `问答记录.md` |
| `cppide/.flower/artifacts/` | 23 个 wave1~wave5 阶段报告 + `architecture.md` + `验收审计.md` + `审计修复.md` 等 |
| `cppide/.flower/scripts/` | 13 个验收脚本:`probe-toolchain.sh` `wave*-verify.sh` `audit-net-failures.sh` `fix-p2-make-verify.sh`,以及 pty 驱动脚本 `wave4-pty-loop.txt` / `wave4-pty-edit.txt` |
| `cppide/runs/manifest.json` | 8.2 KB,每一步的 `session_id` / `ok` / `cost_usd` / `num_turns` / `text` |
| `cppide/runs/sessions.db` | 19.4 MB,原始 transcript |

> 注意:这是 **clone 下来的仓库自己的** `.flower/` 和 `runs/`,
> 与工作目录 `/Users/hechenyu/explore/test-ide/.flower/`、`/Users/hechenyu/explore/test-ide/runs/`
> 是两套不同的东西。本轮对二者**均只读不写**(本报告文件除外)。

---

## 10. 环境零改动证明

本轮执行的全部命令均为只读探测(`date` / `uname` / `ls` / `stat` / `file` / `which` /
`grep` / `head` / `awk` / `brew --prefix` / `brew list` / `xcode-select -p` /
`xcrun --show-sdk-path` / `git clone` / `git rev-parse` / `git ls-remote` /
`git status` / `git log` / `git ls-files`)。

**未执行**:`brew install`、`npm install -g`、`cargo install`、`sudo`、
不带 venv/`--target` 的 `pip install`、`make`(含 `-n`)、`make install`、
任何依赖安装、任何构建、任何启动。

**未修改**:`~/.zshrc`、`~/.zprofile`、`~/.profile`、`PATH`、任何 shell 配置。

**未触碰**:`/Users/hechenyu/explore/test-ide/.flower/notes/` 下已有文件、
`/Users/hechenyu/explore/test-ide/runs/`。

**未对远端做写操作**:无 push、无 PR、无 tag、无 branch 推送。

**新增文件**(仅两处):
1. `/Users/hechenyu/explore/test-ide/cppide/`(`git clone` 结果,working tree 干净)
2. `/Users/hechenyu/explore/test-ide/.flower/artifacts/01-recon.md`(本报告)
