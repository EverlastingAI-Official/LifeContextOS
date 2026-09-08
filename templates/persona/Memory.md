---
schema: lifecontext.persona.memory/v0.1
person_id: local-user
version: 1
review_status: draft
evidence_ids: []
---

# MEMORY — 经审核的长期记忆

> 这是公开仓库中的空白记忆模板，不包含任何真实人物数据。模型生成的内容不能自动成为个人历史。

## 记忆条目模板

### memory_001

- 类型：事件 / 关系 / 决策 / 反思 / 认知变化
- 发生时间：
- 记录时间：
- 内容：
- linked_evidence：
- linked_thought_cells：
- epistemic_status：observed / reported / inferred / disputed
- confidence：
- reviewed_by：
- valid_from：
- valid_to：
- supersedes：
- contradicts：

## 对话记忆规则

- 新对话默认进入会话记录，而不是长期人格。
- 偏好、身份、决定和人生事件只能先成为 `unreviewed` 候选。
- 只有本人确认的候选才能进入后续长期上下文。
- 被拒绝的候选保留审核状态，但不参与人格推理。
