// Call with the two managed ego-browser Page handles for the same selected form.
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

export async function readPosterForm(detailPage, completePage, outputDir) {
  const fields = {};
  let pictures = [];
  let imagePage;
  for (const page of [detailPage, completePage].filter(Boolean)) {
    const snapshot = await page.evaluate(() => {
      const fields = {}, photos = [];
      for (const el of document.querySelectorAll(".label.break-word,.pane-label")) {
        const label = el.innerText.trim();
        if (!["姓名","英文名","生活照","爱好","最爱的电影","座右铭"].includes(label)) continue;
        const row = el.closest(".pane-item,.el-row");
        const value = row?.querySelector(".pane-value,.content");
        if (!value) continue;
        if (label === "生活照") {
          photos.push(...Array.from(value.querySelectorAll("img"), i => i.currentSrc || i.src).filter(Boolean));
        } else {
          const text = value.innerText.split("\n").map(s => s.trim()).filter(s => s && !/^[-—]+$/.test(s)).join("\n");
          if (text) fields[label] = text;
        }
      }
      return { fields, photos: [...new Set(photos)] };
    });
    // Prefer the submitted form. The complete view supplies fields omitted in its summary.
    for (const [key, value] of Object.entries(snapshot.fields)) fields[key] ??= value;
    if (!pictures.length && snapshot.photos.length) {
      pictures = snapshot.photos;
      imagePage = page;
    }
  }
  if (!Object.keys(fields).length) throw new Error("未读到海报字段，请核对当前表单");
  // A fresh private folder prevents stale photos from being reused on a retry.
  await mkdir(outputDir);
  await writeFile(join(outputDir,"表单字段.json"),JSON.stringify(fields),{ flag:"wx",encoding:"utf8" });
  for (const [i, url] of pictures.entries()) {
    const response = await imagePage.fetch(url,{ saveAs:join(outputDir,`生活照-${i+1}.jpg`) });
    if (!response.ok) throw new Error("生活照读取失败，请从该字段下载原始附件");
  }
  return { available:Object.keys(fields), photoCount:pictures.length };
}
