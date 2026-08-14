# 模拟交易平台接入

交易页支持三个账户入口：

- `local`：项目内置的本地历史回放模拟账户。
- `miniqmt`：A 股 miniQMT 账户同步，当前只读。
- `okx_demo`：OKX 官方 Demo Trading 账户同步、策略信号预览和需确认的模拟下单。

## 配置保存方式

miniQMT 和 OKX Demo 都可以直接在面板填写信息。提交前由用户选择保存方式：

- 勾选“保存到本机”：使用 Windows DPAPI 加密，并绑定当前 Windows 用户；下次启动面板时自动读取。
- 取消勾选：配置只保留在当前面板进程内存中；关闭面板后失效，同时删除该平台以前保存的本地配置。
- 点击“清空配置”：同时清除当前进程内存和本机加密文件中的对应平台配置。

加密文件位于 `data/processed/terminal/broker_credentials.bin`，该目录不提交 Git。接口只返回“是否已配置”和“是否本机保存”，不会把账户、密钥或口令返回浏览器。环境变量仍可作为兼容配置来源。

## miniQMT

先启动 QMT 客户端并登录具有量化权限的账户，再在面板输入：

- QMT 用户数据目录，例如 `D:\QMT\userdata_mini`
- 资金账号

运行面板的 Python 环境还必须能导入券商提供的 `xtquant`。不同券商是否提供模拟账户与 API 权限，以券商当前政策为准。

也可用环境变量配置：

```powershell
$env:MINI_QMT_USERDATA_PATH = '券商 QMT userdata_mini 目录'
$env:MINI_QMT_ACCOUNT_ID = '账户号'
```

## OKX Demo

只使用 OKX Demo Trading 创建的 API 凭据，在面板输入 Demo API Key、Secret Key 和 Passphrase。适配器固定发送 `x-simulated-trading: 1`，没有切换实盘的配置项。

也可用环境变量配置：

```powershell
$env:OKX_DEMO_API_KEY = 'Demo API key'
$env:OKX_DEMO_SECRET_KEY = 'Demo secret key'
$env:OKX_DEMO_PASSPHRASE = 'Demo passphrase'
```

### 模拟交易与策略操作

OKX Demo 不是实盘入口。适配器固定携带 `x-simulated-trading: 1`，并且只开放
`*-USDT` 现货市价模拟单。每一笔订单都必须由用户在浏览器二次确认，服务端还会检查
`OKX_DEMO_ONLY` 确认标记；策略预览不会自动提交订单。

面板中的完整流程是：

1. 在“策略”页选择 Gate.io 虚拟货币和交易对，生成候选策略。
2. 打开候选详情，点击“部署到 OKX Demo”。
3. 返回“交易 / OKX Demo”，修改策略参数和单次买入预算。
4. 点击“保存参数并计算信号”。信号使用 OKX 最后一根已完成日线计算。
5. 买入或卖出信号可以填入左侧订单；用户仍需检查数量并二次确认后才会提交模拟单。

所选策略、参数和预算保存在当前浏览器的本地存储中，下次打开面板会自动恢复；点击
“移除策略”会清除这份策略配置。API 密钥仍单独使用 Windows DPAPI 加密文件保存，
不会写入浏览器本地存储。

## 当前边界

miniQMT 目前只同步资金、持仓、未完成委托和最近成交，不调用委托或撤单接口。
OKX Demo 支持上文所述的需确认现货市价模拟单，但不支持撤单、实盘下单或无人值守自动执行。
本地模拟交易仍可完整运行策略历史回放。若未来增加自动执行，还需要先补齐日内亏损、
持仓集中度、频率限制、断线保护和审计日志。
