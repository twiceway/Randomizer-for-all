敌人随机器固定缓存（入库；DEPLOY 同步到 Game\tools）

enemy_index.json（约 16MB，入库）
  - 全图 MSB 扫点；换 CNV 地图包后 GUI「扫描地图」并提交本文件

enemy_slot_prep.json.gz + enemy_slot_prep.meta.json（约 55MB + 侧车，入库）
  - 每槽捐皮池预计算（字段 o = 各目标类 donor id 列表）
  - 改跳过规则后不必重建 prep；生成时会 revalidate + 按需 hydrate（~900 槽约 30～40s，GUI 有进度）
  - enemy_slot_prep.pkl 为本地快载侧车（gitignore），首次读 .gz 后自动生成
  - 构建进程数：默认=本机逻辑核（enemy_gui.prep_workers>0 可覆盖）；与 MSB apply 的 --dynamic-parallel 无关

enemy_slot_density.json + enemy_slot_density.meta.json（入库，第一步离线聚类）
  - 密集区每槽策略：keep_original（1/2）或 dense_pool_1_2（1/2，第二步只抽池1 trash + 池2 elite）
  - 由 build_enemy_slot_density.py 生成；GUI「扫描地图」后自动链式构建
  - index 无 pos_x/y/z 时拒绝构建；index 变更后须重跑 build
  - 契约：.ai/docs/密集槽聚类契约.md

pickup_slot_index.json（T-064 · 入库）
  - 全图 MSB treasure → ItemLot placement；`python cnv_randomizer_core.py pickup-index-export`
  - 换 CNV 地图包后重扫；契约：.ai/docs/T-064_物品槽MSB索引与shuffle重构.md

prep 指纹失效（须重建：python enemy_randomizer_core.py prep 或删 meta 后重新生成）
  - enemy_index.json 变更（重扫 MSB）
  - enemy_archetypes.json 变更
  - dlc_pool_mode 切换（mixed / separate）
  - PREP_VERSION 变更（当前 21）
  - donor_pool_review_manual_excludes.json 变更（donor_review_excludes 指纹）

不必重建 prep（生成时自动处理）
  - 换随机种子
  - 改 GUI 概率矩阵
  - 改跳过规则（hub / 攻城操作员 / talk NPC / exclude 等）
    → revalidate_prep_skip_key 重判 k=npc|hub|siege
    → hydrate_stale_prep_row 为旧误跳过槽补算 o
  - 日志见：prep_skip_revalidated=  prep_pools_hydrated=

维护者改捐皮池 compat 后须手动 prep
  - Boss 封禁、原型表增删、size_tier 辅助、DLC 混池过滤等
  - enemy_categories.json 不入 prep 指纹（跳过类规则靠生成时重判）

真机：spawn 表变后须 MsbEnemyPoc apply-map；仅生成不写 MSB，游戏里不变。

契约：.ai/docs/敌人类别映射契约.md §槽位跳过 · §T-043
