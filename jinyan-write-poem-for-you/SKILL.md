---
name: jinyan-write-poem-for-you
description: "Write classical Chinese poems (五律/七律/五绝/七绝/鹧鸪天/浣溪沙/蝶恋花/唐多令/定风波/临江仙/玉楼春 etc.) strictly imitating the style of poet 晋言 (张伯晋). Triggers on: (1) user asks to compose a poem in 晋言体/晋言风格, (2) writing poems for legal-themed or professional/official contexts, (3) composing 唱和/步韵/次韵 poems, (4) writing poetry for daily life events (travel, work, seasons, illness), (5) any request for classical Chinese poetry where sustained imitation of a specific modern poet is desired. Also use when asked to write a 'poem note' (带注的诗) that contextualizes each work."
---

# 晋言写诗（Jinyan Write Poem for You）

> 作者：张伯晋，笔名晋言。法学博士，法律人诗社社长。诗集《少作集：法理诗情两地书》《无用集》。诗观："诗庄词媚，字短情长"。

## 触发器（Triggers）

用户提到以下任一关键词时触发本skill：
- 晋言体 / 晋言风格 / 仿晋言
- 写首诗，要带注
- 步韵 / 次韵 / 唱和
- 法律人诗 / 法治题材诗
- "诗庄词媚"
- 诗小辑 / 诗辑

## 核心规则

### 1. 格律铁律
- **平水韵为主**（词林正韵可），用新韵或孤雁入群格**必须标注**
- 五律七律严守对仗粘联
- 出律须加注解释

### 2. 每诗必注
每首诗末加"注："交代：
- 创作时间/地点/缘起
- 人物关系
- 地名/典故解释
- 特殊出律说明

### 3. 诗词形式优先级
| 优先级 | 形式 | 说明 |
|--------|------|------|
| 1 | 七律 | 最常用，叙事感怀最佳 |
| 2 | 五律 | 写景/简事 |
| 3 | 鹧鸪天 | 中调最优选 |
| 4 | 浣溪沙 | 小令最优选 |
| 5 | 蝶恋花/玉楼春/定风波/唐多令/临江仙 | 次选 |

### 4. 题材来源（从生活中来）
- **行吟记游**：出差/旅行/通勤路上
- **双城别离**：两地分居，车站送别
- **法律人情**：办案/转隶/法治/法律人工作日常
- **友朋唱和**：步韵/次韵/同题/寄赠
- **病中/节令**：节气、时令、抱恙
- **即事感怀**：日常小事（买房/吃瓜/高铁盒饭）

### 5. 语言特征
- **叠字偶用**：空空、寂寂、纷纷、缕缕、脉脉
- **关键词汇**：缁尘、京国、潇湘、燕山、西山、阑干、青衫、伶仃
- **法言法语自然融**：检察、案牍、公诉、法治——不要刻意堆砌
- **问句收尾**：末联多用问句留余韵
- **口语控制**：偶尔俏皮（嗯嗯复呵呵/卧槽），不可过量
- **双关嵌字**：人名/地名/机构名可藏头，有趣但不强求

### 6. 情感基调
- 孤独与洒脱交织
- 真实事件驱动，不矫情
- 自嘲基因：中年苟且眠、一杯枸杞养吾身
- 人名地名具体，诚意可见

### 7. 典型七律结构
首联→起（点题/写景）
颔联→承（深化/对仗）
颈联→转（感怀/议论）
尾联→合（收束/余韵，常问句）

## 参考文件

完整风格指南（含详细例句对照）：`references/style-guide.md`——作诗前请加载此文件以精确模仿。

## 工作流

1. 确定题目/场景（用户命题或从当前情境取题）
2. 选定体裁（按优先级表）
3. 加载 `references/style-guide.md` 作为格律和用词参考
4. 创作并核验格律
5. 添加注文
6. 如需唱和，附原玉