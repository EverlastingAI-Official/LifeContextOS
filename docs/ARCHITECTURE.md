# MVP 架构

## 1. 数据流

```text
用户授权的数据源
  → 原始文件保险库（哈希、时间、所有者、许可）
  → 转写/解析流水线
  → Evidence 记录
  → ThoughtCell 候选
  → 人工审核与关系确认
  → LifeContext 时间线/图谱
  → Mindcopy 版本
  → 带来源检索的对话与 Agent
  → 评测、反馈、审计日志
```

模型生成内容与用户原始内容必须位于不同命名空间。任何摘要、标签、关系和人格结论都保存生成模型、提示版本、时间、置信度和审核状态。

## 2. 推荐技术形态

首个版本建议采用可通过 Docker Compose 启动的 Web 应用：

- 前端：Next.js + TypeScript；
- API 与 AI 流水线：FastAPI + Python；
- 结构化数据：PostgreSQL；
- 向量检索：pgvector；
- 原始文件：本地对象目录，后续兼容 S3；
- 异步任务：初期使用数据库任务表，规模化后再引入队列；
- 模型适配：统一 Provider 接口，支持本地模型和用户自带 API Key。

不建议 MVP 同时引入图数据库。ThoughtCell 关系先用 PostgreSQL 边表表达；当真实查询证明图数据库有必要时再迁移。

## 3. 服务边界

- `ingestion`：文件接收、哈希、去重、转写、切分。
- `context`：Evidence、ThoughtCell、时间线和关系管理。
- `mindcopy`：人格配置生成、审核、版本和回滚。
- `retrieval`：时间、实体、关键词、向量和关系混合检索。
- `runtime`：对话上下文装配、工具权限和引用生成。
- `evaluation`：盲测集、分项指标、回归对比。
- `governance`：同意记录、访问控制、导出、删除和审计。

## 4. 最小数据模型

- `Person`：主体身份及生命周期元数据。
- `ConsentGrant`：谁允许谁，以何种目的，处理哪些数据，到何时为止。
- `SourceAsset`：原始文件或外部来源。
- `Evidence`：可定位到来源片段的事实记录。
- `ThoughtCell`：语义单元及解释字段。
- `ThoughtRelation`：引用、影响、冲突、演化、派生等有向边。
- `MindcopyVersion`：已确认的身份、价值、风格、记忆索引和运行规则。
- `Conversation` / `Message`：运行记录，明确区分本人、他人和模型输出。
- `EvaluationCase` / `EvaluationRun`：保留题、答案、评分和版本对比。
- `AuditEvent`：所有读取、推断、导出、分享和代理行动。

## 5. 检索策略

一次回答的上下文装配建议按以下顺序：

1. 读取当前 Mindcopy 版本和权限；
2. 识别问题涉及的时间、人物、主题和任务；
3. 以时间过滤 + 关键词 + 向量召回候选 Evidence/ThoughtCell；
4. 展开一跳关系，但限制推断边权重；
5. 重排并保留支持、反对和不确定证据；
6. 生成回答，同时给出来源和置信表达；
7. 将新对话保存为“模型交互”，不能自动冒充个人历史。

## 6. 安全与治理底线

- 默认本地、默认私有、默认不用于模型训练。
- 第三方数据单独标注，支持遮蔽、撤回和最小披露。
- 高敏感数据使用字段级加密；密钥不与密文一起导出。
- 分享 Mindcopy 不应隐式分享全部 Evidence。
- Agent 的“建议”和“代替用户执行”使用不同权限。
- 死后代理、商业交易、公开发布和模型训练分别取得明确授权。
- 删除操作覆盖索引、缓存、派生物和备份策略，并生成删除证明。

## 7. API 草案

```text
POST   /v1/assets
POST   /v1/assets/{id}/process
GET    /v1/thought-cells?from=&to=&topic=
PATCH  /v1/thought-cells/{id}/review
POST   /v1/relations
POST   /v1/mindcopies
POST   /v1/mindcopies/{version}/chat
POST   /v1/evaluations/run
GET    /v1/export
DELETE /v1/persons/{id}
```
