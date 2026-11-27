# 本地运行

Windows 环境需要 Python 3.12、Bahnschrift 和微软雅黑粗体。克隆仓库或安装技能时请保留 `assets/templates/` 目录：该目录包含生活照版的空白底稿和填好的销售样稿。脚本按自身位置定位模板，从任意工作目录运行均可。自定义底稿、样稿可通过 `--blank` 和 `--sales` 指定。证件照专用空白 PSD 和相应框位配置通过 `--id-template`、`--id-layout` 提供。

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

在同一 ego-browser TaskSpace 完成查找、身份和时间核对。打开「审核完整信息」时先监听 popup。详情页和完整页均需等到表单加载，两个照片字段有图片时分别等到图片可读。用实际技能路径导入助手，在本次受限工作目录下指定一个尚未创建的子目录：

```js
const { pathToFileURL } = await import("node:url");
const { readPosterForm } = await import(pathToFileURL(absoluteSkillPath + "/scripts/read_form.mjs"));
const status = await readPosterForm(detailPage, completePage, newPrivateInputDir);
console.log(status); // 仅字段名与图片数量
```

对收集结果核对当前值。在详情缺项时用完整页补齐；如果完整页展示新旧两值或与所选申请相矛盾，核对界面后再定。照片字段只匹配精确名称「生活照」和「证件照」，分别以字段名称和序号保存。返回的 photoCounts 给出各类数量；原有 photoCount 仍表示生活照数量。实际人像字段另有名称时先核对表单定义并只取确认的人像，或使用另行提供的照片。附件预览不清晰时，从对应字段下载原始附件。

## 整理输入和输出

把已核实的内容和翻译整理成 UTF-8 JSON。必填键为 `department`（当前值“销售线”）、`name_cn`、`name_en`（含姓氏）、`movie_cn`、`movie_en`、`hobby_cn`、`hobby_en`、`motto_cn`、`motto_en`。必要时可在座右铭中使用换行。正式制图缺哪项就报告哪项，不拿占位符生成成品。

```powershell
$py = Join-Path $env:LOCALAPPDATA 'zbs-welcome-poster\venv\Scripts\python.exe'
& $py .\scripts\prepare_portrait.py --photo $originalPhoto --out $transparentPng
& $py .\scripts\prepare_portrait.py --photo $idPhoto --keep-background --out $checkedIdPng
& $py .\scripts\render_poster.py --fields $fieldJson --portrait $transparentPng --id-portrait $checkedIdPng --id-template $idTemplate --id-layout $idLayout --output $newDeliveryDirectory
```

变量均指向本次受限目录中的绝对路径。仅在上一步核验成功且已检查原图和蒙版后运行下一步。已在本地手工精修的透明 PNG 可直接作为 `--portrait`。以上示例适用矩形证件照框；若专用模板要求透明人像，处理证件照时省略 --keep-background。两个渲染结果都通过读回核验后，在一个新的目录生成「欢迎海报-生活照版」和「欢迎海报-证件照版」，每版均有 PSD、PNG。旧版单独生成生活照的命令仍可用，省略全部三个 --id- 参数即可。

## 证件照模板的本地配置

先检查 PSD 的画布、背景和图层，使用 RGB、8 位、无前一位新人照片和个人文字的空白底稿。若收到的是成品样稿，先在获准的本地目录整理一份干净副本。版式文件由操作者按实测值填写，坐标单位为画布像素，原点在左上角。

| JSON 字段 | 填写方式 |
| --- | --- |
| `canvas` | 填模板实际的 `[宽, 高]`，渲染时与 PSD 核对。 |
| `photo_box` | 填照片框的 `[左, 上, 右, 下]`。 |
| `photo_mode` | `frame` 保留背景并等比居中裁切填满框；`cutout` 将透明人像等比缩放，底边对齐、水平居中。若居中裁切会损失头顶或下巴，先按实际框的比例准备好构图。 |
| `text_boxes` | 只有在 1700 × 1700 模板逐项核对后确认文字位置与销售稿相同时填 `"sales"`。位置不同则填一个对象，键为下列 17 个图层名，值为实测的四个边界坐标。 |

图层名按配置原样填写：

```text
栏目 电影 EN       栏目 电影 CN
栏目 爱好 EN       栏目 爱好 CN
栏目 座右铭 EN     栏目 座右铭 CN
电影 EN            电影 CN
爱好 EN            爱好 CN
座右铭 EN          座右铭 CN
姓名 EN            姓名 CN
部门 EN            岗位 EN
部门和岗位 CN
```

首次接入的证件照底稿，需要用实际 PSD 和同一人的两种照片做一次版面验收。模板和员工照片留在获准的本机目录。
