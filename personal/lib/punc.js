#!/usr/bin/env node
// 中文听写的标点恢复：调用 sherpa-onnx 的 CT-Transformer 模型。
// 纯英文输入原样返回；模型缺失或推理失败也原样返回，保证不丢字。
//
// 环境变量：
//   VOXTYPE_PUNC_MODEL  指定 onnx 模型路径
//   VOXTYPE_PUNC_DIR    指定模型所在目录（默认 ~/.local/share/voxtype/punct）
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const dir =
  process.env.VOXTYPE_PUNC_DIR ||
  path.join(os.homedir(), ".local/share/voxtype/punct");
const model =
  process.env.VOXTYPE_PUNC_MODEL ||
  [path.join(dir, "model.int8.onnx"), path.join(dir, "model.onnx")].find((f) => fs.existsSync(f));

// CT-Transformer 会在标点两侧输出 token 级空格，把数字（"2 . 0"、"3 . 5 %"、
// "12 : 30"、"2 , 000"、"- 3"）和专名（"GPT -4o"、"TCP / IP"、"C + +"）拆开。
// 只合并明显是副产物的空格，保留正常英文词间距。
const tidy = (text) =>
  text
    // 数字间的 ASCII 标点：2 . 0 / 12 : 30 / 2 , 000
    .replace(/(?<=\d)[ \t]+(?=[.,:;][ \t]*\d)/g, "")
    .replace(/(?<=\d[.,:;])[ \t]+(?=\d)/g, "")
    // 百分号贴回前面的数字：3 . 5 % -> 3.5%
    .replace(/(?<=\d)[ \t]+(?=[%％])/g, "")
    // 正负号贴回数字："- 3.5" -> "-3.5"
    .replace(/(?<=[-+])[ \t]+(?=\d)/g, "")
    // 专名内部的连字符 / 斜杠 / 加号："GPT -4o"、"TCP / IP"、"C + +"
    .replace(/(?<=[A-Za-z0-9])[ \t]+(?=[-/][ \t]*[A-Za-z0-9])/g, "")
    .replace(/(?<=[A-Za-z0-9][-/])[ \t]+(?=[A-Za-z0-9])/g, "")
    .replace(/(?<=[A-Za-z0-9])[ \t]+(?=\+)/g, "")
    .replace(/(?<=\+)[ \t]+(?=[+A-Za-z0-9])/g, "")
    // "Hello . World" -> "Hello. World"
    .replace(/(?<=[A-Za-z])[ \t]+(?=[.,;:!?])/g, "")
    // CJK 标点和括号两边的多余空格
    .replace(/(?<=[\u3400-\u9fff])[ \t]+(?=[，。！？；：、）】》])/g, "")
    .replace(/(?<=[，。！？；：、（【《])[ \t]+(?=[\u3400-\u9fff])/g, "")
    .replace(/(?<=[（【《“])[ \t]+/g, "")
    .replace(/[ \t]+(?=[）】》”])/g, "");

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  input += chunk;
});
process.stdin.on("end", () => {
  const text = input.trim();
  if (!text || !model || !/[\u3400-\u9fff]/.test(text)) {
    process.stdout.write(text);
    return;
  }
  try {
    // 延迟到确认要跑推理再加载原生模块，避免纯英文输入也要付加载成本
    const sherpa = require("sherpa-onnx-node");
    const punc = new sherpa.OfflinePunctuation({
      model: { ctTransformer: model, numThreads: 2, provider: "cpu", debug: 0 },
    });
    process.stdout.write(tidy(punc.addPunct(text).trim()));
  } catch {
    process.stdout.write(text);
  }
});
