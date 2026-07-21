import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Result, Button, Typography } from 'antd';

const { Text } = Typography;

interface Props {
  children: ReactNode;
  /** 自定义错误标题 */
  title?: string;
  /** 出错时的回调(可选,用于上报错误) */
  onError?: (error: Error, info: ErrorInfo) => void;
  /** 自定义兜底渲染 */
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * 通用错误边界组件
 *
 * 用法:
 *   <ErrorBoundary>
 *     <SomeComponent />
 *   </ErrorBoundary>
 *
 * 当子组件抛出渲染异常时,显示友好的错误提示并提供"重试"按钮,
 * 避免整个页面白屏。
 */
class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 控制台输出完整堆栈,便于调试
    console.error('[ErrorBoundary]', error, info.componentStack);
    // 上报回调
    if (this.props.onError) {
      this.props.onError(error, info);
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.handleReset);
      }
      return (
        <Result
          status="error"
          title={this.props.title || '页面渲染出错'}
          subTitle={
            <div>
              <Text type="danger" code>
                {this.state.error.name}
              </Text>
              <Text type="secondary" style={{ marginLeft: 8 }}>
                {this.state.error.message}
              </Text>
            </div>
          }
          extra={[
            <Button type="primary" key="retry" onClick={this.handleReset}>
              重试
            </Button>,
            <Button key="reload" onClick={() => window.location.reload()}>
              刷新页面
            </Button>,
          ]}
        />
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
