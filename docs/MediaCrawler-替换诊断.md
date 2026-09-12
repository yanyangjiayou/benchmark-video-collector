# MediaCrawler 替换诊断（历史技术记录）

> 诊断日期：2026-09-11
> 诊断范围：当前 `benchmark-video-collector` 与 [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) `main` 分支的能力、下载链路、集成成本及风险。
> 文档状态：这是当日的阶段性诊断。此后项目已补充粉丝筛选、小红书浏览器复用、失败分类和相关测试；当前行为以根目录 README 与测试为准。

## 一、结论

**不建议把现有项目整体替换成 MediaCrawler，也没有证据表明直接切换到 MediaCrawler 原生视频下载就一定更稳定。**

原因是当前项目本身已经把 MediaCrawler 当作采集引擎使用：界面、参数校验、日期/点赞筛选、跨批次去重、本地 Whisper 转写、定制 Excel 和历史列表仍由本项目提供。真正可以比较的不是“现有项目 vs MediaCrawler”，而是：

- 现有的定制下载链路；
- MediaCrawler 的原生媒体下载链路；
- 两条链路并存、失败时互相兜底的混合方案。

综合代码实现与上游公开问题，建议选择第三种：**保留当前应用与筛选逻辑，固定一个验证过的 MediaCrawler 版本，将原生下载作为可观测的第二通道，而不是一次性硬切换。**

替换成本判断：

| 方案 | 成本 | 风险 | 建议 |
| --- | --- | --- | --- |
| 仅安装最新版 MediaCrawler，维持现有适配层 | 低到中 | 上游内部 API、浏览器模式、昵称脱敏可能不兼容 | 不直接上线，先固定版本和冒烟测试 |
| 用原生下载完全替掉当前下载代码 | 中 | 可能降低小红书成功率，也会扩大无效下载量 | 不建议 |
| 原生下载 + 当前下载兜底 | 中 | 需要增加策略、指标和真实样本测试 | **推荐** |
| 用 MediaCrawler WebUI 整体替掉当前应用 | 高 | 会丢失转写、业务筛选、历史去重和定制导出 | 不建议 |

还有一个先于技术选型的阻断项：MediaCrawler 使用 [NON-COMMERCIAL LEARNING LICENSE 1.1](https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE)，明确限制为非商业学习/研究用途，并禁止大规模抓取。若本工具服务于跨境电商实际经营，在没有作者书面商业授权前，不应把它作为生产依赖。本文不是法律意见，但该许可风险需要业务负责人确认。

## 二、当前系统实际架构

当前仓库不是一个等待接入 MediaCrawler 的独立爬虫，而是一个 **MediaCrawler 适配应用**。

```text
网页表单与登录确认
        │
        ▼
本项目规则与任务编排
        │
        ├─ 小红书：MediaCrawler 获取元数据 → 本项目详情页下载兜底
        │
        └─ 抖音主页：本项目继承 MediaCrawler Crawler
                      → 监听正常网页作品列表
                      → 本项目下载符合条件的视频
        │
        ▼
日期/点赞/视频类型筛选 → ID 与 SHA-256 去重
        │
        ▼
faster-whisper 本地转写 → 定制 Excel → 历史批次列表
```

证据：

- [`mvp/pipeline.py`](../mvp/pipeline.py#L139-L148) 直接调用 `vendor/MediaCrawler` 的 Python 环境和入口。
- [`mvp/crawler_worker.py`](../mvp/crawler_worker.py#L22-L73) 对抖音主页采集进行了继承和覆盖，只下载筛选后的新视频。
- [`mvp/douyin_page.py`](../mvp/douyin_page.py) 监听抖音正常网页的作品列表响应，并用登录浏览器上下文下载视频。
- [`mvp/xhs_video.py`](../mvp/xhs_video.py#L18-L117) 在 MediaCrawler 没拿到小红书视频时，从详情页补取。
- [`mvp/pipeline.py`](../mvp/pipeline.py#L168-L297) 完成业务筛选、历史去重、转写和定制导出；这些都不是简单换成上游 WebUI 后可以原样保留的能力。

所以，“替换”应理解为升级或调整底层采集/下载实现，而不是替换整个仓库。

## 三、功能需求匹配度

根据当前 README、界面、规则模型和测试，需求与两边能力的关系如下：

| 功能需求 | 当前项目 | MediaCrawler 单独使用 | 诊断 |
| --- | --- | --- | --- |
| 小红书、抖音 | 支持 | 支持，另支持更多平台 | 匹配 |
| 指定博主主页 | 支持 | 支持 creator 模式 | 匹配 |
| 关键词采集 | 支持入口 | 支持 search 模式 | 基础匹配 |
| 按起止日期筛选 | 采集后精确筛选 | 没有等价的统一精确区间参数 | 仍需保留本项目逻辑 |
| 最低点赞筛选 | 支持 | 没有等价的统一前置筛选 | 仍需保留本项目逻辑 |
| 最多 N 条、只保留视频 | 支持 | 有采集数量，但媒体类型和业务上限语义不同 | 仍需适配 |
| 跨批次跳过已完成内容 | SQLite 记录平台 + 内容 ID，并用视频哈希二次去重 | 存储层能力不等价于当前业务历史 | 不能直接替代 |
| 仅成功下载/转写后才记为完成 | 支持 | 不提供当前业务语义 | 不能直接替代 |
| 本地语音转写 | faster-whisper | 不提供 | 必须保留当前项目 |
| 指定八列 Excel | 支持 | 上游为通用内容/评论/创作者导出 | 不能直接替代 |
| 历史批次与下载入口 | 支持 | 上游 WebUI 有数据预览/导出，但不是当前历史模型 | 不能直接替代 |
| 独立登录态、手动验证码 | 当前设计目标 | 支持登录态与 Playwright/CDP | 可集成，但需固定配置 |
| 关闭评论、代理，限制并发为 1 | 已显式传参 | 支持 | 匹配 |
| 粉丝数门槛 | 界面和模型有字段 | 上游可取得部分创作者信息，但最新版教学版不保留完整创作者资料 | **当前也未真正执行筛选** |

整体匹配度可以概括为：

- 作为“平台元数据采集引擎”：高，约 80%。
- 作为“完整产品替代”：低，约 35%～45%。
- 作为“原生视频下载器替代”：无法只凭项目名或口碑判定，需要真实样本 A/B 测试。

百分比是架构评估值，不是实测成功率。

## 四、下载稳定性对比

### 4.1 抖音主页模式

当前定制链路有几项对稳定性有利的措施：

- 从登录后的正常博主页面监听作品列表，而不是完全依赖单独的创作者 API；
- 在下载前完成日期、点赞、视频类型、历史记录筛选，减少请求量；
- 从 `play_addr`、`play_addr_h264`、`play_addr_256` 多组地址中去重后依次尝试；
- 校验 HTTP 状态与 MP4 `ftyp` 标记；
- 先写 `.part`，完成后原子替换，避免留下看似成功的半文件。

相关实现见 [`mvp/douyin_page.py`](../mvp/douyin_page.py) 和 [`mvp/crawler_worker.py`](../mvp/crawler_worker.py)。

MediaCrawler 当前原生实现也支持抖音媒体下载，但默认配置 `ENABLE_GET_MEIDAS = False`；开启后，它从视频对象中选择一组 URL，再调用客户端取得媒体并直接写文件。参考上游 [`config/base_config.py`](https://github.com/NanmiCoder/MediaCrawler/blob/main/config/base_config.py)、[`media_platform/douyin/core.py`](https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/core.py) 和 [`store/douyin/douyin_store_media.py`](https://github.com/NanmiCoder/MediaCrawler/blob/main/store/douyin/douyin_store_media.py)。

静态代码比较没有显示原生实现比当前实现多出明显的重试、完整性校验或原子写入保障。对“指定博主、只下载满足条件的新视频”这个场景，当前实现反而更贴近需求。

**判断：抖音主页模式不应硬切到原生下载。** 可以把原生客户端请求作为当前多 URL 尝试全部失败后的备用通道。

### 4.2 小红书模式

MediaCrawler 原生实现会优先从 `origin_video_key` 构造视频地址，缺失时再取 H.264 stream URL，然后通过平台客户端下载。当前项目则在上游未产出文件时打开笔记详情页，同时从页面状态、可见 `video` 元素和网络响应里找候选地址，并验证响应类型和文件大小。

两种方式覆盖的是不同失败面，组合价值高于互相替换：

- 原生结构化字段路径更快，但字段变化或返回空值时会直接失败；
- 当前详情页观察路径更慢，但能覆盖结构化 `video_url` 缺失的情况；
- 页面路径同样会受登录状态、风控、DOM 变化和视频水印影响。

上游公开 issue 中，2026 年仍有人报告 [`video_url` 为空导致小红书视频无法下载](https://github.com/NanmiCoder/MediaCrawler/issues/953)，也有仍未关闭的[小红书视频水印问题](https://github.com/NanmiCoder/MediaCrawler/issues/813)。另有[仅查看与下载即触发平台风控的报告](https://github.com/NanmiCoder/MediaCrawler/issues/915)。这些个案不能证明 MediaCrawler 整体不稳定，但足以说明“换成原生下载必然更稳”没有可靠依据。

**判断：小红书应保留现有详情页兜底。** 最合理的顺序是原生结构化下载优先，失败后进入当前详情页逻辑，并记录每条视频由哪条通道成功。

### 4.3 关键词模式

这里存在一个比替换更直接的现有缺口：

- MediaCrawler 默认关闭媒体下载；
- 当前管线只为小红书补取缺失视频；
- 抖音自定义下载只覆盖 `creator` 方法，关键词 `search` 仍走上游默认逻辑。

因此，**抖音关键词模式很可能只能得到元数据，无法得到可转写视频**。这需要真实环境复核，但从代码路径看风险很高。简单开启上游原生媒体下载虽然能补视频，却会在业务日期/点赞筛选之前下载扫描到的内容，增加带宽、耗时和平台请求，违背“小规模、只下载命中结果”的设计目标。

正确修复方向是给抖音关键词结果也加“先筛选、后下载”的适配层，而不是全局打开上游媒体下载。

## 五、升级到最新版会引入的兼容风险

### 5.1 使用了上游内部 API

当前代码依赖并修改了这些非稳定公共接口：

- `CrawlerFactory.CRAWLERS`；
- `DouYinCrawler.create_douyin_client`；
- `DouYinLogin.begin`；
- `store.douyin._extract_video_download_url`；
- `CDPBrowserManager`；
- 若干具体目录名与 JSONL 字段。

目前 `main` 分支仍能看到这些符号，但它们不是有版本承诺的 SDK 接口。任何上游重构都可能使登录、下载或结果解析在运行时才报错。当前 README 只写“取得兼容版本”，没有固定 commit/tag，因此新机器安装出来的行为不可复现。

### 5.2 浏览器模式默认值变化

最新版默认启用 CDP，并默认连接已经开启远程调试的浏览器；上游 README 还要求较新的 Chrome。当前登录 worker 显式设置了 `CDP_CONNECT_EXISTING = False`，但小红书正式采集直接运行上游 `main.py`，没有等价地固定该值。这样登录确认与正式采集可能使用不同浏览器上下文，也可能等待用户开启日常浏览器远程调试，与项目“独立浏览器目录”的约束不一致。

参考：上游 [`README.md`](https://github.com/NanmiCoder/MediaCrawler#-chrome-浏览器配置推荐) 和 [`config/base_config.py`](https://github.com/NanmiCoder/MediaCrawler/blob/main/config/base_config.py)。

### 5.3 昵称与创作者资料已脱敏

最新版教学版会对昵称做中间脱敏，对用户 ID 做哈希，并且不再落库完整创作者资料。参考 [`tools/user_hash.py`](https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/user_hash.py)、[`store/xhs/__init__.py`](https://github.com/NanmiCoder/MediaCrawler/blob/main/store/xhs/__init__.py) 和 [`store/douyin/__init__.py`](https://github.com/NanmiCoder/MediaCrawler/blob/main/store/douyin/__init__.py)。

当前 Excel 的“博主账号”在没有手工备注时直接使用上游 `nickname`。升级后，这一列会变成类似“博***号”的值，历史列表也会继承脱敏值。若业务必须显示完整公开昵称，需要重新定义合规的数据来源与字段，而不是直接改掉上游的隐私设计。

### 5.4 运行环境与依赖更重

上游当前要求 Python 3.11+，并包含 Playwright、数据库驱动、OpenCV、Pandas、Matplotlib 等依赖。参考 [`pyproject.toml`](https://github.com/NanmiCoder/MediaCrawler/blob/main/pyproject.toml)。本机系统 Python 是 3.9.6，必须由 `uv` 创建独立 3.11+ 环境；不能直接使用系统 Python。

### 5.5 平台风控不是换库能消除的问题

MediaCrawler 的核心仍是浏览器自动化、登录态和平台 Web 接口。账号状态、Cookie、验证码、IP、访问节奏、页面/API 变化都可能导致失败。上游也有近期的[小红书登录后接口失败案例](https://github.com/NanmiCoder/MediaCrawler/issues/855)和[风控导致浏览器断开案例](https://github.com/NanmiCoder/MediaCrawler/issues/791)。

因此，“某份代码下载更稳定”可能只对某个版本、账号、地区、浏览器和时间窗口成立，不能外推成长期稳定性结论。

## 六、当前项目中与替换无关、但应先修的功能缺口

### 高优先级

1. **粉丝门槛未生效（后续版本已修复）**：诊断当日 `CollectionRequest.min_followers` 和网页输入存在，但 [`mvp/pipeline.py`](../mvp/pipeline.py) 尚无粉丝数筛选逻辑。
2. **抖音关键词视频下载链路不完整**：如 4.3 所述，默认配置下没有可靠媒体文件，因而无法完成转写。
3. **上游版本未锁定**：README 让用户取得“兼容版本”，但没有 commit、tag、校验值或兼容矩阵。
4. **小红书登录确认与正式采集可能使用不同 CDP 策略**：存在登录明明成功、正式任务却重新要求登录的风险。

### 中优先级

1. **对上游兼容性缺少启动前检查**：现有 healthcheck 只检查目录、许可证和 Python 包，不验证所需类、方法、CLI 参数及结果字段。
2. **失败日志判断依赖字符串**：平台错误文案变化后，可能把失败当成空结果或给出错误提示。
3. **下载成功缺少业务级质量指标**：目前主要看文件是否存在；没有统一记录通道、HTTP 尝试数、文件时长、是否只有音频、是否带水印。
4. **真实平台测试覆盖不足**：单元测试覆盖规则、去重和抖音主页定制流程，但没有上游版本契约测试，也没有关键词媒体链路测试。

这些缺口意味着，即使立即换成最新版，也可能只是把问题从“下载失败”变成“登录态不一致、账号字段脱敏、下载了大量不命中的视频或上游接口变更”。

## 七、成本估算

以下为有测试账号、可手动完成验证码前提下的工程估算，不包含等待平台解除风控或申请商业授权的时间。

### 方案 A：只升级上游，维持现状

- 固定 commit、重建环境、增加兼容性检查：0.5 天；
- 修浏览器配置和昵称字段预期：0.5 天；
- 小红书/抖音各两种入口冒烟测试：0.5～1 天。

合计约 **1～2 人日**。代码改动不大，但验证不能省。

### 方案 B：双下载通道，推荐

- 抽象统一下载接口与失败分类：0.5～1 天；
- 接入上游原生下载作为主通道或备用通道：0.5 天；
- 补抖音关键词的“先筛选、后下载”：0.5～1 天；
- 指标、契约测试、真实样本 A/B：1～2 天。

合计约 **2.5～4.5 人日**。这是能实际回答“是否更稳定”的最低可靠成本。

### 方案 C：整体换成上游 WebUI

需要重新实现或迁移业务筛选、转写、成功态去重、八列 Excel、历史批次和现有交互，预计至少 **5～10 人日**，且最终仍会维护一层定制代码，没有明显收益。

## 八、建议实施与验收方式

如果之后决定改，建议按以下顺序，而不是一次替换：

1. 先确认许可：仅学习验证，或取得书面商业授权；否则停止技术接入。
2. 固定 MediaCrawler 的具体 commit，并记录源码归档 SHA-256。
3. 增加启动前契约检查，验证所依赖的类、方法、CLI 参数、目录和 JSONL 字段。
4. 修复抖音关键词媒体链路和粉丝门槛语义。
5. 将下载器做成策略：`native -> existing fallback`，并允许按平台单独开关。
6. 用固定样本做 A/B：小红书与抖音各至少 20 条，覆盖新旧视频、长短视频、低高赞、主页和关键词入口。
7. 至少记录：元数据成功率、视频下载成功率、可解码率、下载耗时、重试数、文件大小、是否带水印、是否仅音频、触发风控次数。
8. 只有当新策略在相同账号、网络和样本下不劣于现有基线，且无新增风控，再逐步放量。

推荐验收门槛：

- 已选中视频的下载成功率不低于现有链路；
- 所有“成功”文件均可被 ffprobe/Whisper 解码，不以文件存在代替成功；
- 不下载日期、点赞、历史去重后已经排除的内容；
- 单次仍保持并发 1、上限 50、评论与代理关闭；
- 登录态只存于独立目录，不连接日常浏览器用户目录；
- 失败可回退到原实现，且不会把失败内容写入完成历史；
- Excel 八列、历史列表和二次去重结果保持不变。

## 九、最终建议

**暂不做硬替换。**

最优下一步不是“把代码换掉”，而是先做一个小范围可靠性改造：锁定上游版本、修复现有两项功能缺口、加兼容性检查，再将 MediaCrawler 原生下载作为第二通道进行 A/B。这样既能验证别人所说的“更稳定”是否在你的账号和网络下成立，也保留随时回滚的能力。

若仅为了指定博主的视频采集，现有抖音链路的筛选前置、多 URL 尝试、内容校验和原子写入设计并不弱，没有充分理由删除。小红书则最适合双通道互补。

## 十、本次诊断的验证边界与后续状态

- 已静态检查当前仓库的 README、规则、采集、下载、登录、历史、导出及测试代码。
- 已查阅 MediaCrawler 当前公开 README、配置、命令行、抖音/小红书核心与存储实现，以及相关公开 issue。
- 诊断当日未执行真实账号平台采集；后续开发阶段已完成抖音和小红书真实流程冒烟验证，但这不构成长期成功率保证。
- 后续已在项目虚拟环境运行完整测试套件。GitHub 下载到全新电脑后仍应重新运行测试和平台冒烟验证。
- 当前电脑有可运行的 MediaCrawler 本地快照，但它没有自身 Git 元数据，无法还原准确 commit；该第三方目录按许可和体积要求不上传，换机时需按 README 重新取得并验证兼容性。

## 参考资料

- [MediaCrawler 项目说明](https://github.com/NanmiCoder/MediaCrawler)
- [MediaCrawler 配置](https://github.com/NanmiCoder/MediaCrawler/blob/main/config/base_config.py)
- [MediaCrawler 命令行参数](https://github.com/NanmiCoder/MediaCrawler/blob/main/cmd_arg/arg.py)
- [MediaCrawler 抖音实现](https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/core.py)
- [MediaCrawler 小红书实现](https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/core.py)
- [MediaCrawler 许可证](https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE)
- [本项目 README](../README.md)
- [本项目第三方说明](../THIRD_PARTY_NOTICES.md)
