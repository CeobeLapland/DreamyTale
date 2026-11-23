# C 初版阅读器

从项目根目录启动（Python 3.11+）：

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.c_demo:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/reader/ ，不要直接双击 HTML。前端使用同源 API，无 Node 构建依赖，无模型密钥。

## 已实现
官方 ZIP 上传及书目选择、导入任务轮询、书架、后端视频/逐页视频播放、无视频时原图阅读、翻页、字幕、文字交互、录音及语音文件上传、回答音频播放、浏览器朗读降级、插话暂停、回答后续播、静态页点击识别、交互结果 JSON 导出、真实错误提示。

录音需要 localhost 或 HTTPS，最长一分钟；上传音频最多 20 MB。音频在联调入口读完后丢弃，不持久化。浏览器朗读只是客户端降级，不代表后端 TTS 已接入。官方 ZIP 中选择中文绘本01～03或英文绘本01～03，上传会导入所选一本，不是整个包的六本。

## 接口核查与 A/B 待办

- POST /api/books/ingest/upload 已支持 multipart archive、book_key；当前只接受官方 ZIP（PDF + 同名 TXT + WAV 目录），单 PDF/照片上传未实现。
- GET /api/books、书籍详情、capability、generation-result、scene-plan、assets 均已对接。
- POST generate 已存在，但默认 UnavailableGenerationRunner，会失败；A/B 需要接入 pipeline，前端不会伪造生成成功。
- POST interact 已有检索/热区/QA 卡等规则能力，尚无通用 ASR/LLM/TTS。
- 新增独立入口 c_demo.py 的 POST /api/interact/audio：multipart audio + request(JSON InteractionRequest)。已验证音频上传，返回明确 fallback；A/B 接入 ASR 后才能真正语音问答。没有调用外部模型或产生费用。
- 回答 audio_path 按书内 assets 相对路径消费；若后端改为公共音频 URL，需补充媒体契约。
- 视频动态对象点击尚未实现：不能将静态页热区直接套到移动的视频对象。当前只在原图上点击。
- history_turn_ids 已发送，但后端缺少持久化会话/多轮理解接口；前端记录仅保留在内存，刷新清空，可手动导出。
- 审核写入 API、Query 批量评测尚未实现；导出的是交互耗时和响应，不是自动判分正确率。
- 目前没有认证，原后端 CORS 允许全部来源、ingest 可接收服务端文件路径；仅本地联调，不直接暴露公网。
- 团队文档“任意 PDF/照片”是开发目标；比赛输入仍限授权素材。

## 验收
1. 上传官方 ZIP，选择一本，观察导入进度、页面及文字。
2. 在已有生成产物的书籍检查视频、翻页时间轴、字幕。
3. 发文字搜索/问题，确认 fallback 不显示为成功。
4. 点击录音后停止，或上传 WAV，确认音频抵达后端并明确报告 ASR 缺失。
5. 检查空音频、不支持格式、无书籍、断网、生成失败。
6. A/B 接好模型后验证回答音频结束续播、视频中的语音检索及第二本书。

界面调整：点击“上传绘本”直接打开文件选择器，选完官方 ZIP 后在弹窗选择其中一本再导入。取消选择不发请求。阅读页不再展示系统能力和提取文字调试区。


## 更新：PDF 阅读上传与音频回听

阅读页面现使用 POST /api/reader/uploads（multipart file）检查上传，再使用 POST /api/reader/import（upload_id、key）创建导入任务。旧官方素材导入接口保留供评测使用，阅读上传不再需要 TXT/WAV；此前仅支持官方 ZIP 的说明已被本节替代。

- PDF 直接导入；ZIP 中只有一本 PDF 直接导入，多本才显示实际文件列表。
- 文件最大 300 MB；ZIP 内单个 PDF 最大 100 MB；PDF 最多 200 页。扫描页需后续 OCR，不会伪造提取文字。
- 每次导入使用新的 book-随机编号，不覆盖已有书籍；默认语言中文，文件名含“英文”时设为英文，尚未自动检测语言。
- 绘本保存于 data/books/<book_id>/source/book.pdf，页面在 pages/，描述在 book.json；临时上传在 temp/uploads/reader，导入结束清理。取消多本选择后临时上传暂时保留，需后续增加过期清理。
- 音频上传已改为按钮；录音/上传的音频在聊天区可回听。播放回听会暂停故事和其他回答音频。音频回听使用浏览器内存 URL，切换书籍或关闭页面释放，不跨刷新保存。
- 后端仍未配置 ASR/通用问答/TTS，上传与回听成功不代表已能语音回答。
- 新入口仍为 backend.app.c_demo:app，修改 Python 后需重启服务。

验证：python -m frontend.check_reader_upload；python -m frontend.check_integration。
