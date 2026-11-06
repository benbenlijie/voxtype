# Voxtype 中文语音后处理实施计划

> **给代理开发者：** 必须按任务逐项执行；可使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`。每次修改先写测试，测试失败后再实现；提交只包含本计划列出的文件。

**目标：** 将本机验证过的简体转换、中文标点恢复和空格修整变成可移植、可选安装、依赖及模型来源清楚的 Voxtype 后处理配套。

**架构：** 使用 Voxtype 已有的 `[output.post_process]` 命令接口，不改 Rust 识别路径。处理器从标准输入读取转写文本，依次做繁转简、中文标点恢复及保守空格修整；任何处理失败都输出原文。模型权重在安装时单独获取，不纳入 Git。

**技术栈：** Node.js、`sherpa-onnx-node`、CT-Transformer ONNX 标点模型、Voxtype 配置中的 `output.post_process`。

---

## 文件职责

- `extras/chinese-postprocess/voxtype-zh-post`：稳定命令入口，负责读取标准输入、调用处理步骤和失败回退。
- `extras/chinese-postprocess/punc.js`：本地中文标点恢复及标点后的空格整理。
- `extras/chinese-postprocess/package.json`、锁文件：固定 JavaScript 运行依赖。
- `extras/chinese-postprocess/README.md`：运行时依赖、模型来源、模型许可待核实项及无模型降级行为。
- `extras/chinese-postprocess/tests/`：不访问网络、不需要真实模型的单元测试；标点推理层以替身测试。
- `extras/chinese-postprocess/models/`：仅放下载说明或 `.gitkeep`，不跟踪权重。
- `config/default.toml`：通过项目基础计划提供的可移植命令接入示例。

## 任务 1：拆出可独立测试的空格修整逻辑

**文件：**
- 新建：`extras/chinese-postprocess/tests/tidy.test.mjs`
- 修改：`extras/chinese-postprocess/punc.js`
- 新建：`extras/chinese-postprocess/package.json`

- [ ] **步骤 1：写空格修整输入输出测试**

覆盖 `2 . 0 -> 2.0`、`12 : 30 -> 12:30`、`3 . 5 % -> 3.5%`、`GPT -4o -> GPT-4o`、`TCP / IP -> TCP/IP`、`C + + -> C++`、`Hello . World -> Hello. World`、中文标点两侧无多余空格、正常英文词间空格不变。

- [ ] **步骤 2：先运行测试**

运行：`cd extras/chinese-postprocess && npm test`

预期：因测试或 `tidy` 导出入口不存在而失败。

- [ ] **步骤 3：提取并导出 `tidy(text)`**

从当前本机 `punc.js` 搬入对应规则，保留原本注释并导出函数供测试调用；所有整理应只处理明确的空格伪影，不改写词义或普通空格。

- [ ] **步骤 4：重跑测试**

运行：`cd extras/chinese-postprocess && npm test`

预期：所有空格修整用例 PASS。

- [ ] **步骤 5：提交**

```bash
git add extras/chinese-postprocess/punc.js extras/chinese-postprocess/package.json extras/chinese-postprocess/tests/tidy.test.mjs
git commit -m "test: cover Chinese punctuation spacing cleanup"
```

## 任务 2：建立不依赖真实模型的处理逻辑测试

**文件：**
- 新建：`extras/chinese-postprocess/tests/test_pipeline.mjs`
- 修改：`extras/chinese-postprocess/punc.js`
- 修改：`extras/chinese-postprocess/package.json`

- [ ] **步骤 1：写管线替身测试**

将文本转换和标点模型调用抽成可注入函数，测试：纯英文跳过中文标点模型；中文输入调用标点模型；空输入保持空；模型缺失时保留已完成的简体转换；模型抛错时回传有效文本；修整只对模型输出应用。

- [ ] **步骤 2：确认测试先失败**

运行：`cd extras/chinese-postprocess && npm test`

预期：导入的函数尚不存在导致失败。

- [ ] **步骤 3：实现可注入处理函数**

实现 `processText(text, { toSimplified, restorePunctuation })`。生产命令负责加载依赖；纯处理函数不得在导入时访问模型路径或联网。

- [ ] **步骤 4：运行管线和空格测试**

运行：`cd extras/chinese-postprocess && npm test`

预期：所有本地测试 PASS，无模型下载请求。

- [ ] **步骤 5：提交**

```bash
git add extras/chinese-postprocess/punc.js extras/chinese-postprocess/package.json extras/chinese-postprocess/tests/test_pipeline.mjs
git commit -m "test: isolate Chinese postprocessing pipeline"
```

## 任务 3：制作为通用命令并提供原文回退

**文件：**
- 新建：`extras/chinese-postprocess/voxtype-zh-post`
- 修改：`extras/chinese-postprocess/punc.js`
- 新建：`extras/chinese-postprocess/tests/test_cli.sh`

- [ ] **步骤 1：写命令行合同测试**

用临时替身程序运行入口，验证标准输入被处理后写到标准输出、诊断只写标准错误、空白输入不启动模型、处理程序返回非零或空输出时回退原文，且退出不泄露识别内容到日志。

- [ ] **步骤 2：先运行合同测试**

运行：`bash extras/chinese-postprocess/tests/test_cli.sh`

预期：入口脚本不存在而失败。

- [ ] **步骤 3：实现可移植入口**

脚本以自身所在目录定位 `punc.js` 和安装的 Node 运行时；优先使用 `PATH` 中的 `node`，不写入个人 Node 版本路径。依赖命令失败时必须输出输入原文。处理器自身不得保存输入文本到临时文件。

- [ ] **步骤 4：运行命令行测试**

运行：`bash extras/chinese-postprocess/tests/test_cli.sh && cd extras/chinese-postprocess && npm test`

预期：两组测试 PASS。

- [ ] **步骤 5：提交**

```bash
git add extras/chinese-postprocess/voxtype-zh-post extras/chinese-postprocess/punc.js extras/chinese-postprocess/tests/test_cli.sh
git commit -m "feat: add portable Chinese postprocess command"
```

## 任务 4：核对繁转简、标点模型依赖和许可

**文件：**
- 修改：`extras/chinese-postprocess/package.json`
- 新建：`extras/chinese-postprocess/README.md`
- 新建：`extras/chinese-postprocess/model-source.md`
- 修改：`extras/chinese-postprocess/tests/test_cli.sh`

- [ ] **步骤 1：记录当前本机实现的外部依赖**

检查当前用户目录下的 `~/.local/bin/voxtype-zh-post`、`~/.hermes/bin/voxtype-t2s` 和 `~/.local/lib/voxtype-punc/punc.js`；只抽取功能与依赖事实，不把任何个人路径或二进制文件复制进仓库。

- [ ] **步骤 2：加入依赖源和许可核对项**

文档列出繁转简工具、`sherpa-onnx-node` 与模型的正式来源、版本和各自许可。若任一来源/许可无法从随包许可或正式发布页核实，保持该步骤为发布阻断项，不声称可自由再分发。

- [ ] **步骤 3：确定依赖管理方式**

锁文件固定 JS 依赖版本；模型下载脚本只从已核实的正式来源下载，支持 `--model-dir` 和自定义地址，不把远程脚本管道直接交给 shell。用户可只装繁转简/空格修整，不下载标点模型。

- [ ] **步骤 4：运行无网回归**

运行：`cd extras/chinese-postprocess && npm ci --ignore-scripts && npm test`

预期：依赖按锁文件安装，单测不请求标点模型；真实模型验收单独标注为需要用户下载模型。

- [ ] **步骤 5：提交**

```bash
git add extras/chinese-postprocess/package.json extras/chinese-postprocess/package-lock.json extras/chinese-postprocess/README.md extras/chinese-postprocess/model-source.md extras/chinese-postprocess/tests/test_cli.sh
git commit -m "docs: document Chinese postprocess dependencies and model sourcing"
```

## 验收

- [ ] `cd extras/chinese-postprocess && npm ci && npm test` 通过。
- [ ] `bash extras/chinese-postprocess/tests/test_cli.sh` 通过。
- [ ] 扫描 `extras/chinese-postprocess`，确认其中没有个人绝对路径或 `.hermes` 私有目录引用。
- [ ] 不存在被跟踪的 `.onnx` 或模型权重。
- [ ] 配置示例接入后，`cargo test config:: --lib` 通过。
