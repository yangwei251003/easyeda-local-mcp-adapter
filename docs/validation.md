# 开源候选验证记录

核查日期：2026-10-26。

## 已通过的范围

环境：Windows、Python 3.12.6、官方 MCP Python SDK 2.1.0。

实际执行 `python test_adapter.py`，**9 / 9 测试通过**：

另在独立新建的 Python 虚拟环境中，按 `requirements.txt` 从包源安装 SDK 与依赖后再次执行同一测试，**9 / 9 再次通过**。未借用原软件的私有环境配置，也未修改系统 Python 环境。

1. 非法执行输入在发送前拒绝。
2. 没有连接窗口时不发送执行请求。
3. HTTP 执行错误标注结果可能不确定，不自动重试。
4. 服务身份不匹配时不认为 Bridge 已连接。
5. 同时发现多个 Bridge 时拒绝自行选择。
6. 多窗口只路由到明确指定的已连接窗口。
7. HTTP 重定向不跟随。
8. 使用实际 MCP SDK 客户端与 stdio 子进程，初始化、列工具、查询状态及缺少窗口 ID 的拒绝逻辑通过。
9. 超时后不重试，模拟服务只收到一次执行请求。

HTTP 服务均为测试主动创建的回环模拟服务器，端口由系统分配。MCP 测试子进程通过 fixture 只访问该模拟端口；没有扫描正式 49620—49629 端口，没有启动 Node Bridge、打开 EasyEDA 或读写真实设计。

## 公开整理

- 保留完整适配器与隔离测试，补齐固定的 SDK 依赖。
- 原本机 Python、项目目录与 Node 绝对路径不公开。Node 从 PATH 查找，官方 Skill 目录可通过环境变量配置。
- 不包含原 `bridge.log`、现用 MCP 配置、历史连接报告或 EDA 工程。
- MIT 仅用于原创适配器与文档，第三方组件通过官方链接单独安装。

## 尚未验证

- 新版 EasyEDA 客户端与官方 Bridge 的实际兼容性。
- 真实 EDA 窗口中的执行、设计保存、原理图与 PCB 一致性、DRC、制造资料或实板功能。
- Linux / macOS、第二台物理电脑及不同 SDK 版本。

这些隔离测试证明协议适配与相应错误处理行为，不能替代真实 EDA 项目验证。真实执行可能改动设计，操作前仍须核对目标窗口、工程、文档类型与每个 API 的准确签名；执行结果不明确时先查状态，不能盲目重试。

## 依赖与接口来源

- [官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 与 [2.1.0 发布页](https://pypi.org/project/mcp/2.1.0/)：SDK 来源与固定版本。
- [EasyEDA 官方 API Skill](https://github.com/easyeda/easyeda-api-skill)：Bridge 身份、回环端口范围与 HTTP 接口。
- [Run API Gateway](https://github.com/easyeda/eext-run-api-gateway)：客户端扩展的来源。

本仓库没有复制这些第三方源码或分发包。
