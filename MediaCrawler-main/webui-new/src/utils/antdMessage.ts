// 全局 message holder:让 message 静态调用能消费 ConfigProvider/App 上下文
// 解决 antd 警告: [antd: message] Static function can not consume context like dynamic theme
//
// 用法:
//   1. App.tsx 用 antd <App> 组件包裹应用,并在内部用 App.useApp() 调 bindMessageApi 注入实例
//   2. 业务代码把 `import { message } from 'antd'` 改为 `import { message } from '../utils/antdMessage'`
//      原 message.success()/message.error() 等调用代码无需修改
import { message as staticMessage } from 'antd';

// 动态 message 实例(由 App.useApp() 注入,能消费 ConfigProvider 主题上下文)
// 在 App 挂载前为 null,此时降级到 antd 静态 message(功能正常,只是不消费动态主题)
// 注:App.useApp() 返回的 MessageInstance 与 antd 导出的静态 message 类型签名略有差异
// (静态 message 含 config/useMessage 等方法),此处用 any 接收,导出侧仍保持静态类型
let dynamicApi: any = null;

export function bindMessageApi(api: any) {
  dynamicApi = api;
}

// 代理对象:优先转发到动态实例,降级到静态实例
// 这样所有 message.success/error/warning/info/loading 调用都走同一入口,
// 且在 App 挂载后自动消费 ConfigProvider 上下文,消除 antd 静态方法警告
export const message: typeof staticMessage = new Proxy({} as typeof staticMessage, {
  get(_target, prop: string) {
    const api = (dynamicApi || staticMessage) as any;
    const fn = api[prop];
    // 绑定 this,避免解构丢失上下文(如 message.success.bind(api))
    return typeof fn === 'function' ? fn.bind(api) : fn;
  },
});
