# ESAE AGENTS.md — 开发铁律（不可谈判）

## 架构铁律
1. L3 内核纯 stdlib，不可 import 任何第三方库
2. L3 不持有 API key，零 token 消耗
3. 独立 PID，不依赖 Hermes 会话存在
4. 审计日志写入失败 = ESAE 停止

## 模块铁律
5. 每个模块有 `__init__.py` 导出公共接口
6. 所有异常继承 ESAEError
7. 全量类型注解，模块级+函数级 docstring

## 变异铁律
8. genome 变异不新增/不删除键，只改数值
9. 禁止 exec()、compile()、setattr() 运行时代码生成
10. 变异前必须保存快照，失败自动回退

## 测试铁律
11. kernel/* 测试覆盖率 100%
12. 行为契约式测试（测关系不变性，不测具体数值）
13. 集成测试必须通过后方可声称 Phase 完成

## 引用
参考 Hermes AGENTS.md 规范 + ESAE V1 终极实施计划
