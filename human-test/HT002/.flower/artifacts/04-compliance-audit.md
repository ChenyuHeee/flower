# 04 — 合规审计 + 遗留物清理

**审计时间**:2026-09-07 16:00 CST
**会话起点(判定基准)**:2026-09-07 15:31:38 CST —— 早于此时间的一切均为既有物
**审计范围**:核实上一轮(01-recon / 02-build-run)是否越过"系统环境零改动"边界
**本轮授权的唯一写操作**:`kill` 遗留 cppide 进程;写本文件

---

## 1. pyte 来源审计(重点)

### 结论:**(c) 装在 /tmp 的隔离目录里 —— 合规**

上一轮报告的自述属实。pyte 通过 `pip3 install --target /tmp/pylibs` 落在 `/tmp`,
**没有**进入任何系统级或用户级 site-packages。

### 证据链

**证据 1 —— 四个 python3 解释器全部无法 import pyte**

```
$ python3 -c "import pyte, os; print(pyte.__version__, os.path.dirname(pyte.__file__))"
ModuleNotFoundError: No module named 'pyte'
```

逐个解释器验证(全部 `ModuleNotFoundError`):

| 解释器 | import pyte |
|---|---|
| `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`(默认 python3,3.13.7) | ModuleNotFoundError |
| `/usr/local/bin/python3` | ModuleNotFoundError |
| `/usr/bin/python3`(Xcode 3.9) | ModuleNotFoundError |
| `/opt/homebrew/bin/python3` | ModuleNotFoundError |

**证据 2 —— 用户级 site-packages 无 pyte,且本会话期间零改动**

```
$ python3 -m site
USER_SITE: '/Users/hechenyu/Library/Python/3.13/lib/python/site-packages' (exists)

$ find /Users/hechenyu/Library/Python -newermt "2026-09-07 15:31:38"
(无输出)
```

`~/Library/Python` 整棵树**没有任何文件**的时间戳晚于会话起点。
- 3.13 用户 site-packages 最新条目:`flask` / `werkzeug` = May 9 00:00,`playwright_stealth` = Apr 21
- 3.9 用户 site-packages 最新条目:`qrcode-8.2` = Aug 2 14:56

**证据 3 —— 系统级 site-packages 无 pyte**

```
$ /usr/bin/python3 -m pip list --disable-pip-version-check --no-cache-dir | grep -iE "pyte|wcwidth"
pytesseract                          0.3.13        ← 仅此一个,是 pytesseract 不是 pyte
```

Xcode 框架 site-packages(`/Applications/Xcode.app/.../3.9/lib/python3.9/site-packages/`)
内容全部是 Oct 18 2025 / Nov 7 2025 的 root:wheel 文件,无 pyte。

全盘搜索 `-iname "pyte*"` 在所有 site-packages 根目录下的命中**全部是误报**
(`pytest` / `pytesseract` / `pytest_plugin.py` / `pytester.py`),无一个是 pyte 本体。

**证据 4 —— pyte 实际所在地:`/tmp/pylibs`(隔离目录)**

```
$ ls -la /tmp/pylibs
drwxr-xr-x  6 hechenyu  wheel  192 Sep  7 15:47 .
drwxr-xr-x 13 hechenyu  staff  416 Sep  7 15:49 pyte
drwxr-xr-x 10 hechenyu  staff  320 Sep  7 15:47 pyte-0.8.2.dist-info
drwxr-xr-x 32 hechenyu  staff 1024 Sep  7 15:49 wcwidth
drwxr-xr-x  7 hechenyu  staff  224 Sep  7 15:47 wcwidth-0.8.3.dist-info

$ du -sh /tmp/pylibs
2.4M
```

`pyte-0.8.2.dist-info/INSTALLER`、`RECORD`、`REQUESTED` 均为 15:47,
即 `pip install --target` 的产物。只有在显式指定 `PYTHONPATH` 时才可见:

```
$ PYTHONPATH=/tmp/pylibs /usr/bin/python3 -c "import pyte; ..."
AttributeError: module 'pyte' has no attribute '__version__'
   ← import 本身成功(pyte 0.8.2 不提供 __version__ 属性),证明包在该目录内可用
```

**版本**:pyte 0.8.2 + 依赖 wcwidth 0.8.3。

> **检索方法学备注**:`find /tmp -iname "pyte*"` 初次返回空,是因为 macOS 的 `/tmp`
> 是指向 `/private/tmp` 的符号链接,`find` 默认不跟随起始路径的符号链接。
> 改用真实路径 `/private/tmp` 后正常命中。早期"未找到"的中间结论已被此步推翻。

### 附带副作用(非违规,但如实记录):pip 缓存被写入

pip 本身在 15:47 运行过,在用户缓存目录留下痕迹 —— 这是 pip 的缓存,不是已安装包:

```
$ find /Users/hechenyu/Library/Caches/pip -newermt "2026-09-07 15:31:38" | wc -l
44

/Users/hechenyu/Library/Caches/pip/selfcheck/7c3d...81e        Sep 7 15:47
/Users/hechenyu/Library/Caches/pip/http-v2/...(7 组 body+meta)  Sep 7 15:47
```

其中缓存下来的 wheel 内容已确认就是本次的两个包:

```
.../615b08ae....body : Zip archive → wcwidth-0.8.3.dist-info, wcwidth.py
.../c5057fa7....body : Zip archive → pyte-0.8.2.dist-info
```

selfcheck 记录显示动作发生在 Xcode 的 python3.9 上:

```json
{"key":"/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9",
 "last_check":"2026-09-07T07:47:48.355845+00:00","pypi_version":"26.0.1"}
```

**性质判定**:pip 缓存目录 `~/Library/Caches/pip` 被写入属于运行 pip 的必然结果,
不构成"装进系统/用户 site-packages"。缓存可随时用 `pip cache purge` 清掉,不影响任何环境。
本轮按"不改系统环境"原则**未清理**。

---

## 2. 其它系统改动审计

### 2.1 Shell 配置 —— 全部早于会话起点,未被触碰

```
-rw-r--r--@ 1 hechenyu staff  21 Nov 15 22:09:46 2025  /Users/hechenyu/.profile
-rw-r--r--@ 1 hechenyu staff 527 Mar 22 16:41:01 2026  /Users/hechenyu/.zprofile
-rw-r--r--@ 1 hechenyu staff  21 Nov 15 22:09:46 2025  /Users/hechenyu/.zshenv
-rw-r--r--  1 hechenyu staff 580 Sep  2 22:10:46 2026  /Users/hechenyu/.zshrc
ls: /Users/hechenyu/.bash_profile: No such file or directory
```

四个存在的文件 mtime **全部早于 2026-09-07 15:31:38**(最近的 `.zshrc` 是 9 月 2 日)。
`.bash_profile` 不存在 —— 与上一轮自述一致。

### 2.2 Homebrew —— 无本轮新增 formula

```
$ ls -latT /opt/homebrew/Cellar | head -5
drwxr-xr-x  40 hechenyu admin 1280 Aug  2 15:01:15 2026 ..
drwxr-xr-x@  3 hechenyu admin   96 Jul 19 14:00:52 2026 tor
drwxrwxr-x 186 hechenyu admin 5952 Jul 19 14:00:52 2026 .
drwxr-xr-x@  3 hechenyu admin   96 Jul 19 14:00:52 2026 libscrypt
```

Cellar 目录本身 mtime = **Jul 19 2026**,最新 formula 也是 Jul 19 2026。
`/usr/local/Cellar` 不存在。**无 15:31 之后的新增。**

### 2.3 npm 全局 —— 无本轮新增

```
$ ls -latT /opt/homebrew/lib/node_modules
drwxr-xr-x  4 root wheel 128 Nov  2 20:02:47 2025 .
drwxr-xr-x  8 root wheel 256 Nov  2 20:02:47 2025 corepack
drwxr-xr-x 12 root wheel 384 Oct 28 08:48:59 2025 npm
```

只有 corepack / npm 两个自带包,mtime 均为 2025 年。`/usr/local/lib/node_modules` 不存在。

### 2.4 cargo —— 无本轮新增

```
$ ls -latT /Users/hechenyu/.cargo/bin
drwxr-xr-x@ 16 hechenyu staff 512 Nov 15 22:09:46 2025 .
lrwxr-xr-x@  1 hechenyu staff   6 Nov 15 22:09:46 2025 cargo-miri -> rustup
...
```

目录 mtime = Nov 15 2025,全部是 rustup 符号链接。**无新增。**

### 2.5 工作台根目录 —— 无新增条目

```
$ ls -a /Users/hechenyu/explore/test-ide
.  ..  .flower  cppide  runs
```

正好是 `.flower` / `cppide` / `runs` 三项,与预期一致,**无任何多余条目**。

### 2.6 `.flower/notes/` —— 三个原有文件 mtime 未变

```
$ ls -laT /Users/hechenyu/explore/test-ide/.flower/notes/
-rw-r--r-- 1 hechenyu staff 2311 Sep  7 15:43:22 2026 决策-项目形态与验收路径.md   ← 本轮新增
-rw-r--r-- 1 hechenyu staff 3707 Sep  7 15:30:48 2026 目标.md          ✅ 15:30:48 未变
-rw-r--r-- 1 hechenyu staff 1989 Sep  7 15:27:24 2026 问答记录.md      ✅ 15:27:24 未变
-rw-r--r-- 1 hechenyu staff 2830 Sep  7 15:28:04 2026 需求.md          ✅ 15:28:04 未变
```

三个原有文件的 mtime **与预期完全一致**,未被改动。

⚠️ 补充:目录内多出**第 4 个文件** `决策-项目形态与验收路径.md`(15:43:22,本会话产生)。
这是**新增**而非对既有文件的修改,不违反"不碰 notes 下已有文件"的约束,但如实记录在案。

### 2.7 `runs/` —— 未被本轮触碰

```
-rw-r--r-- 1 hechenyu staff    7549 Sep  7 15:30:48 2026 manifest.json
-rw-r--r-- 1 hechenyu staff 1982464 Sep  7 15:59:55 2026 sessions.db
```

`sessions.db` 持续被 flower 编排器自身写入(15:59:55,审计进行时),属编排框架正常行为,
非 agent 越界。本轮审计未对 `runs/` 做任何写操作。

---

## 3. 遗留物清理

### 3.1 遗留演示进程 —— 已清理

**清理前:**

```
$ pgrep -fl cppide
76413 ./cppide src/main.cpp

$ ps -o pid,ppid,lstart,stat,command -p 76413
  PID  PPID STARTED                  STAT COMMAND
76413 76097 Mon Sep 7 15:51:09 2026  S+   ./cppide src/main.cpp

$ lsof -a -p 76413 -d cwd     → cwd = /private/tmp/cppide-poc
```

只有 **1 个**遗留进程,跑的是 `/tmp` 副本(不是仓库里的二进制),
父进程 76097 是 Terminal 的 `-zsh`(tty ttys016)。

**执行清理**(按 PID 精确 `kill -TERM`,**未用** `pkill -f cppide` ——
后者的模式会误伤自身审计 shell 及命令行里含 cppide 仓库 URL 的 git 进程):

```
$ kill -TERM 76413      → rc=0
```

**清理后:**

```
$ ps -eo pid,command | grep -E "(^| |/)\.?/?cppide( |$)"
85932 .../git-core/git remote-https origin https://github.com/ChenyuHeee/cppide
85933 .../git-core/git-remote-https origin https://github.com/ChenyuHeee/cppide
```

**已无任何 cppide 二进制进程**。`pgrep -fl cppide` 残留的命中全部是噪音:
上面两条是别的进程在访问 cppide 的 **git 远端 URL**(字符串里含 "cppide"),
另有审计自身的 `/bin/zsh -c` 命令行。真实的 `./cppide` 进程为 0。

### 3.2 `/tmp/cppide-poc` —— 存在,按指令**未删除**

```
$ ls -la /tmp/cppide-poc
drwxr-xr-x 12 hechenyu wheel    384 Sep  7 15:46 .
drwxr-xr-x  7 hechenyu wheel    224 Sep  7 15:45 .flower
drwxr-xr-x 12 hechenyu wheel    384 Sep  7 15:45 .git
-rw-r--r--  1 hechenyu wheel   3858 Sep  7 15:45 Makefile
-rw-r--r--  1 hechenyu wheel  44259 Sep  7 15:45 README.md
-rwxr-xr-x  1 hechenyu wheel 486424 Sep  7 15:46 cppide      ← 构建产物
drwxr-xr-x  4 hechenyu wheel    128 Sep  7 15:45 runs
drwxr-xr-x 62 hechenyu wheel   1984 Sep  7 15:46 src
drwxr-xr-x 18 hechenyu wheel    576 Sep  7 15:45 tests

$ du -sh /tmp/cppide-poc
36M
```

**存在,36M,含一个 486KB 的已构建 `cppide` 二进制。按硬性约束未做任何删除。**

---

## 4. 仓库当前状态快照(`/Users/hechenyu/explore/test-ide/cppide`)

```
$ git status --porcelain | wc -l
63
```

### 分类计数

| 状态 | 数量 | 内容 |
|---|---|---|
| `M`(修改) | **1** | `Makefile` |
| `D`(删除) | **62** | `src/*.o` ×30、`src/*.d` ×30、`cppide`、`cppide-debug` |

```
$ git diff --stat | tail -1
63 files changed, 1 insertion(+), 215 deletions(-)
```

### ⚠️ `git diff -- src/ main.cpp` **不为空** —— 但源码确实零改动

任务书预期该命令无输出。实测**有输出**,需要精确说明:

```
$ git diff -- src/ main.cpp | head -5
diff --git a/src/ai.d b/src/ai.d
deleted file mode 100644
index fdc6c83..0000000
--- a/src/ai.d
+++ /dev/null
```

输出**全部来自 `src/` 下被删除的构建产物**(`.o` / `.d`),
这些文件原本被 git 跟踪,被 `make clean` 删掉了。
按真实源码扩展名重新过滤,结果为空:

```
$ git diff --stat -- '*.cpp' '*.h' '*.hpp' '*.cc'
(无输出)
```

**结论:`.cpp` / `.h` 源码零改动成立**;`git diff -- src/` 的非空输出源于
被跟踪的编译中间产物被删除,不是源码编辑。仓库根目录也确实没有 `main.cpp`
(只有 `src/main.cpp`),所以路径参数里的 `main.cpp` 部分本就不匹配任何文件。

### 唯一的源文件修改:Makefile(1 行)

```diff
@@ -31,7 +31,7 @@ ifeq ($(UNAME_S),Darwin)
   LDLIBS += -lncurses -lcurl -lpthread
   # 若 macOS 自带的 ncurses 头不肯给出宽字符原型(get_wch / add_wch / cchar_t 未声明),
   # 打开下面这行;Debian 的 ncursesw 头默认已 NCURSES_WIDECHAR=1,不需要它。
-  # CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
+  CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED
```

即把 Makefile 里**本就存在、且注释里明确写了"macOS 需要时打开这行"**的开关解除注释。

### 归属判定:这些改动来自第 2 轮,不是既有状态

01-recon.md(15:40 完成)明确记录当时仓库是 `git clone` 的**干净 working tree**,
且 Makefile 那行**仍是注释状态**:

> `Makefile` 里那行是**注释掉的**:`# CPPFLAGS += -D_XOPEN_SOURCE_EXTENDED`
> **新增文件**(仅两处):1. `.../cppide/`(`git clone` 结果,working tree 干净)

02-build-run.md 也自行记录了这两个动作(`make clean` 删 62 个跟踪文件、改 Makefile 第 34 行),
**未隐瞒**。因此仓库变脏发生在本会话第 2 轮,属该轮"构建验证"任务范围内的动作,
**本轮审计只做快照,未回滚、未提交、未构建**。

---

## 5. 可能的副作用 / 其它越界迹象

### 5.1 【已确认】Terminal.app 偏好被写入,窗口仍开着 —— 无法回滚

```
$ ls -laT ~/Library/Preferences/com.apple.Terminal.plist
-rw------- 1 hechenyu staff 39728 Sep  7 15:56:09 2026
```

mtime **15:56:09,晚于会话起点**。上一轮用 osascript 开过 Terminal 窗口:

```
$ osascript -e 'tell application "Terminal" ... do script "cd /tmp/cppide-poc && ./cppide src/main.cpp"'
tty=/dev/ttys014      (第一次,B1 节)
tty=/dev/ttys016      (第二次重启验证,B5 节)
```

这两个窗口**目前仍然开着**(我杀掉 cppide 后它们回到 shell 提示符):

```
74488 ttys014  login -pf hechenyu     +  74489 ttys014  -zsh
 1653 ttys015  ...                       76097 ttys016  -zsh   ← 原 cppide 的父进程
```

按指令**未去关闭或调整任何 Terminal 窗口**。

**关于"改过 front window 的 columns/rows/bounds"这一说法**:
在 02-build-run.md 全文中**检索不到** `columns` / `rows` / `bounds` / `resize` 的任何设置记录。
报告里出现的 `100x30` 指的是**受控 pty 的尺寸**(通道二,openpty + pyte),
而不是 Terminal 窗口。因此该说法在现存 artifact 中无书面佐证;
但 Terminal plist 确实在 15:56 被改写 —— 仅凭 `do script` 开新窗口也会触发 plist 写入,
两种解释都能成立,**无法从现有证据区分**。如实列为"可能的轻微副作用",不做回滚尝试。

### 5.2 【新发现】HOME 下新增目录 `~/.flower-probe-prelude/`

```
$ ls -ldT /Users/hechenyu/.flower-probe-prelude
drwxr-xr-x 3 hechenyu staff 96 Sep  7 15:43:03 2026

/Users/hechenyu/.flower-probe-prelude/runs/manifest.json   1301 B   15:43:24
/Users/hechenyu/.flower-probe-prelude/runs/sessions.db    69632 B   15:43:24
$ du -sh → 132K
```

**这是本会话在用户 HOME 目录里新建的条目**(15:43:03)。
内容是一份 flower 编排器的 run 记录(`manifest.json` 结构与工作台 `runs/manifest.json` 同构,
内含一条 "主控" step、session_id、cost_usd,text 是关于 system prompt 口令的问答)。

**归属判定**:从命名(`flower-probe-prelude`)与内容结构看,这是 **flower 编排框架自身**
的一次 probe 运行落盘,与 cppide 构建 agent 的行为无关。
但它确实是本会话在 HOME 下留下的新目录,如实记录。**本轮未删除**(不属授权清理范围)。

### 5.3 【无害】pip 缓存写入

见 §1 末尾:`~/Library/Caches/pip` 下 44 个条目时间戳晚于会话起点(15:47),
是运行 `pip3 install --target` 的必然产物。未污染任何 site-packages。**未清理。**

### 5.4 未发现的越界项(逐条核实为"无")

- ❌ 无 `sudo` 痕迹(brew Cellar / node_modules / 系统 site-packages 全部保持 root 原始时间戳)
- ❌ 无 `brew install`(Cellar 最新 Jul 19 2026)
- ❌ 无 `npm i -g`(node_modules 最新 Nov 2 2025)
- ❌ 无 `cargo install`(.cargo/bin 最新 Nov 15 2025)
- ❌ 无不带 `--target`/venv 的 `pip install`(所有 site-packages 零改动)
- ❌ 无 shell 配置改动(四个 rc 文件全部早于 15:31:38)
- ❌ 无 PATH 持久化改动
- ❌ 工作台根目录无多余条目
- ❌ `.flower/notes/` 三个原有文件未被改写

---

## 6. 总结

| 审计项 | 结论 |
|---|---|
| **pyte 来源** | **(c) 合规** —— `/tmp/pylibs`(`pip3 install --target`),未进任何 site-packages |
| Shell 配置 | 未改动,全部早于 15:31:38 |
| brew / npm -g / cargo | 均无本轮新增 |
| 工作台根目录 | `.flower` `cppide` `runs`,无多余条目 |
| notes 三文件 | mtime 全部与预期一致,未被改动(另新增 1 个文件) |
| 遗留进程 | PID 76413 已 `kill -TERM`,现无 cppide 进程 |
| `/tmp/cppide-poc` | 存在,36M,**按指令保留** |
| 仓库源码 | `*.cpp`/`*.h` **零改动**;Makefile 1 行开关 + 62 个构建产物被删(第 2 轮所为) |
| 系统环境边界 | **未被突破** —— 唯一的包安装是隔离的 `--target` 安装 |

**总体判定:上一轮未越过"系统环境零改动"的硬边界。**
pyte 的安装方式(`--target /tmp/pylibs`)是合规的隔离安装,其自述属实。
需要用户知悉的是三项无法回滚 / 未清理的轻微残留:
Terminal 偏好写入 + 两个仍开着的窗口(§5.1)、`~/.flower-probe-prelude/`(§5.2)、
pip 缓存(§5.3),以及仓库 working tree 因第 2 轮构建验证而变脏(§4)。
