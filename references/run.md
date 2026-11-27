# 本地运行

Windows 环境需要 Python 3.12、Bahnschrift 和微软雅黑粗体；两份原 PSD 默认位于当前用户桌面，分别为 `【交付】新人欢迎-空白.psd`、`【交付】新人欢迎-销售.psd`。也可通过 `--blank` 和 `--sales` 传入实际路径。客户模板由本地提供。GitHub 包只包含技能、脚本和依赖清单。

以下在技能目录用 PowerShell 执行。已安装环境可直接从第二步开始。

```powershell
$runtime = Join-Path $env:LOCALAPPDATA 'zbs-welcome-poster\venv'
uv venv --python 3.12 $runtime
$py = Join-Path $runtime 'Scripts\python.exe'
uv pip install --python $py -r .\requirements.txt
& $py .\scripts\prepare_portrait.py --setup-models
```

模型从其发布方下载一次，校验 SHA-256 后缓存于本机。照片处理和排版在本机完成。

## 读取选定的表单

在同一 ego-browser TaskSpace 完成查找、身份和时间核对。打开「审核完整信息」时先监听 popup。详情页和完整页均需等到表单加载，生活照字段有照片时等到图片可读。用实际技能路径导入助手，在本次受限工作目录下指定一个尚未创建的子目录：

```js
const { pathToFileURL } = await import("node:url");
const { readPosterForm } = await import(pathToFileURL(absoluteSkillPath + "/scripts/read_form.mjs"));
const status = await readPosterForm(detailPage, completePage, newPrivateInputDir);
console.log(status); // 仅字段名与图片数量
```

对收集结果核对当前值。在详情缺项时用完整页补齐；如果完整页展示新旧两值或与所选申请相矛盾，核对界面后再定。附件预览不清晰时，从生活照一栏点下载原始附件。

## 整理输入和输出

把已核实的内容和翻译整理成 UTF-8 JSON。必填键为 `department`（当前值“销售线”）、`name_cn`、`name_en`（含姓氏）、`movie_cn`、`movie_en`、`hobby_cn`、`hobby_en`、`motto_cn`、`motto_en`。必要时可在座右铭中使用换行。正式制图缺哪项就报告哪项，不拿占位符生成成品。

```powershell
$py = Join-Path $env:LOCALAPPDATA 'zbs-welcome-poster\venv\Scripts\python.exe'
& $py .\scripts\prepare_portrait.py --photo $originalPhoto --out $transparentPng
& $py .\scripts\render_poster.py --fields $fieldJson --portrait $transparentPng --output $newDeliveryDirectory
```

变量均指向本次受限目录中的绝对路径。仅在上一步核验成功且已检查原图和蒙版后运行下一步。已在本地手工精修的透明 PNG 可直接作为 `--portrait`。脚本保留空白稿图层，新增 17 个可编辑文字层和置顶人物层，读回核对文字与合成图，再在新的交付目录输出 `欢迎海报.psd` 和 `欢迎海报.png`。
