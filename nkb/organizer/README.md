# 独立记忆整理器

该模块只在启用整理且有队列任务时请求配置的模型。原始事件应先由宿主可靠保存，再调用 `enqueue(library_id, receipt_ids)`；关闭整理不会删除或阻止原始存储。库配置在 `brain.meta.organizer_profile`，不接受密钥字段。

```python
worker = Organizer(
    data_dir,
    snapshot=lambda library_id: locked_snapshot(library_id),
    apply=lambda library_id, plan: locked_apply_and_persist(library_id, plan),
    credential=lambda library_id, profile: private_keystore_lookup(library_id, profile),
    read_archive=lambda library_id, receipt_id: owned_archive_lookup(library_id, receipt_id),
)
```

`snapshot` 返回本库 `Brain.to_dict()` 的独立快照。`apply` 在同一库的写锁/事务中调用 `apply_plan(brain, plan, library_id)`，并持久化成功后再返回。模型网络请求发生在两个 callback 之间，不占图谱锁。`credential` 可返回密钥字符串，或运行时 `{api_key, base_url, model}`，后者可复用宿主已配置的 provider。该返回值不会写入配置、队列或错误消息。`transport(request, *, timeout)` 可注入离线测试，默认标准库 HTTPS transport 禁止重定向。

`raw_ids` 优先为 capture receipt ID，依据节点 `meta.evidence.archive_receipt_id` 定位；也兼容直接节点ID。`read_archive` 可返回 normalized、record.normalized 或 record.record.normalized 的完整归档对象。已标注截断的节点在没有完整归档时明确失败，不假装已整理全文。长记录按角色/字符游标分批处理，末尾不会被静默丢弃。

默认 `cadence=batch`，达到 batch_size 自动批处理，尾批最多等待约30秒；`cadence=session` 每个完成turn可触发一批。`run_once(library_id, flush=True)` 可手动冲刷尾批。`preview` 只读取当前材料和计数，不调用凭证或模型。近24小时的调用与材料字符预算持久保存；字符预算计入发送材料JSON，不等于模型token计费。

模型只能提出 remember/merge/supersede/relate/candidate。JSON严格限制字段、操作数量、现实域与确定性；证据必须逐字来自本批本库指定角色。活跃事实的正文使用用户原话摘录，模型概括另记为未确认的语义说明；模型给出的别名供 `semantic_recall` 做有出处的查询扩展。助手自述不能成为用户事实，角色扮演、假设和不确定结果进入候选。工具观察保留真实outcome并明确不是用户确认事实。自动修改旧事实仅适用于同语义key、同层、未被用户编辑或保护的整理结果；重要设定不会被自动盖掉。人格只能形成候选，明确审阅后才可导入。

任务使用SQLite租约、重试和已验证计划缓存；apply失败不需要再次调用模型。库之间的队列、预算和tombstone独立。`status` 返回有限状态/错误信息，不回显服务端正文或凭证。

`rollback` 只撤回当前仍未被后续修改的最近整理结果，不删除原始事件；已被编辑的结果会拒绝回滚。`review_candidate` 支持明确采用/拒绝，角色扮演与未知现实域不能被当成现实事实采用。

隐私遗忘必须由宿主在本库图谱事务中删除/禁用来源与派生记忆，并调用 `forget_plan_data` 清理 organizer 日志和候选的证据拷贝。随后调用 `worker.forget(library_id, raw_ids, node_ids)`：它会对该库取消队列、清除所有 job 输入/计划/结果正文、清空 items，保留最小ID tombstone；无关原始事件不动，可重新排队。每次输入、apply前后均检查取消epoch，停止或遗忘后的迟到响应不能写回计划或结果。SQLite启用 secure_delete，并尽可能 checkpoint(TRUNCATE) 清除旧WAL页；返回 checkpointed 反映实际结果。

测试使用离线 transport 与临时库，尚未测试任何真实模型API的JSON稳定性、延迟或语义准确率。

## 严格累计阈值（0.4.2）

`auto_trigger_count` 是每库整数 `0..500`，与每次请求的 `batch_size` 分开：

- `0` 保持旧配置的 soft batch 兼容：不足一批时最多等待约30秒。
- `1..500` 且 `cadence=batch` 时严格累计；未达到 N 条不会因为等待30秒而调用模型。
- `cadence=session` 仍按每个完整轮次处理，不受批量阈值限制。
- `run_once(..., flush=True)` 是用户主动立即整理，可以绕过累计阈值，但不能绕过启用开关、凭证、调用和字符预算。

达到阈值时，用 SQLite `drain_items` 快照当前已经累积的待处理原文。实际请求仍受每批最多12条、输入字符预算限制；当次积累会分批排空，不会因为第一批处理6条后剩下14条小于20，就把尾部永远搁置。这个快照在重启和预算暂停后保留；期间新到的记录等待下一轮阈值，不无限延长当前轮次。长原文的分片游标和旧重试任务可继续，不要求再新增 N 条。

`status` 与 `preview` 增加 `trigger`：`mode`（strict/legacy/session）、`threshold`、`pending`、`cohort_pending`、`partial_pending`、`eligible`、`draining`、`remaining`、`below_threshold`。预览仍不读取凭证、不调用模型。多库轮询会跳过未达阈值或预算已耗尽的库。

已由录入来源校验确认的原文 alias 不重复送模型：历史待处理项会标为 `done_alias`，整批已成为 alias 的旧任务标为 `aliased`；原文和存档没有删除。混合旧任务只省略 alias 材料，继续处理其他真实原文。只有可能重复、窗口不明或证据不足的记录不会被静默跳过。`recording_group` 是采集通道来源，不是多条独立事实证据。

## 可验证的机器 JSON 记录

模型可在每个操作中输出：

```json
{"atom":{"subject":"user","predicate":"home.city","value":"北京","qualifiers":{"polarity":"affirmed"}}}
```

`subject` 只能是 user/agent/tool 固定角色或证据中出现的实体短名；`predicate` 是简短稳定属性标识；`value` 必须逐字出现在已验证的证据完整语句中。限定项仅允许 `polarity`、证据字面的 `scope`、`unit`，模型不能写时间、库归属、代码或任意对象。常见否定与肯定限定矛盾，以及复杂否定会进入候选。

程序保存 `node.meta.memory_atom`：

```text
schema = love-house-memory-atom/v1
library_id, subject, predicate, value, qualifiers, layer, key
relation_status = model_extracted | verbatim_fallback
domain, certainty
valid_from, valid_to, event_at, recorded_at
evidence = [{id,role,receipt_id,source_event_at}, ...]
```

库归属、有效期和记录时间由程序补充，不接受模型提供。`model_extracted` 表示有逐字值和来源约束的模型关系抽取，不等于程序已经证明整条自然语言关系的语义正确率。旧模型输出没有 atom 时，会生成保留完整原话的 `verbatim_fallback`，不会把模型概括冒充原文。

相同 subject/predicate/value/qualifiers/layer 的新表述可合并到一个事实节点，保留第一次原话和完整来源；不同值不能用 merge 混到旧事实中，需明确 supersede 或人工审阅。过期旧事实的 atom 有效期同步关闭。`organizer_summary` 仍供人类理解/检索，界面正文保留实际原话，不强迫用户阅读机器 JSON。

`organizer_evidence` 保存最近24条带引文的界面证据；`organizer_sources` 和 `memory_atom.evidence` 保存全部轻量来源引用，不因重复次数超过24而丢弃早期出处。宿主的遗忘关系闭包必须同时读取这些来源 ID；备份恢复必须递归映射 receipt 引用。

新增离线验收覆盖严格阈值1/3/20、未达阈值零调用、快照尾批、新记录另起一轮、手动冲刷、重启/预算/失败、长片进度、多库公平、机器值与时间校验、语义相同跨措辞合并、28条来源保留、否定、不同值审阅以及确认 alias 不重复付费。
