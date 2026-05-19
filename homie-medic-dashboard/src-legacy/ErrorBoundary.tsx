/**
 * ErrorBoundary — bắt mọi lỗi render không xử lý của React component tree.
 * Hiển thị thông tin debug + nút Reload thay vì blank screen.
 */
import * as React from 'react';

interface Props {
  children: React.ReactNode;
}
interface State {
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error('[Homie Medic] React render crash:', error);
    console.error('Component stack:', errorInfo.componentStack);
    this.setState({ error, errorInfo });
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <div style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#020617',
          color: '#f1f5f9',
          fontFamily: 'system-ui, sans-serif',
          padding: '24px',
        }}>
          <div style={{ maxWidth: 720, width: '100%' }}>
            <div style={{
              padding: '24px',
              background: '#0f172a',
              border: '1px solid #ef4444',
              borderRadius: '16px',
              boxShadow: '0 20px 40px rgba(239, 68, 68, 0.15)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <div style={{
                  width: 40,
                  height: 40,
                  borderRadius: '50%',
                  background: 'rgba(239, 68, 68, 0.15)',
                  color: '#ef4444',
                  display: 'grid',
                  placeItems: 'center',
                  fontWeight: 700,
                  fontSize: 22,
                }}>!</div>
                <div>
                  <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Lỗi hiển thị dashboard</h1>
                  <p style={{ margin: '4px 0 0 0', fontSize: 13, color: '#94a3b8' }}>
                    React component crash khi render. Chi tiết bên dưới.
                  </p>
                </div>
              </div>

              <div style={{
                background: '#020617',
                border: '1px solid #1e293b',
                borderRadius: '8px',
                padding: '12px 16px',
                fontFamily: 'monospace',
                fontSize: 12,
                color: '#fca5a5',
                marginBottom: 12,
                wordBreak: 'break-word',
              }}>
                <strong>{this.state.error.name}:</strong> {this.state.error.message}
              </div>

              {this.state.error.stack && (
                <details style={{ marginBottom: 12 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 12, color: '#94a3b8', userSelect: 'none' }}>
                    Stack trace
                  </summary>
                  <pre style={{
                    background: '#020617',
                    border: '1px solid #1e293b',
                    borderRadius: '8px',
                    padding: '12px 16px',
                    fontSize: 11,
                    color: '#64748b',
                    overflow: 'auto',
                    maxHeight: 240,
                    marginTop: 8,
                  }}>{this.state.error.stack}</pre>
                </details>
              )}

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => window.location.reload()}
                  style={{
                    padding: '10px 16px',
                    background: '#3b82f6',
                    color: 'white',
                    border: 0,
                    borderRadius: '8px',
                    fontWeight: 600,
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                >Reload trang</button>
                <button
                  onClick={() => { window.location.href = '/auth/logout'; }}
                  style={{
                    padding: '10px 16px',
                    background: 'transparent',
                    color: '#94a3b8',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    fontWeight: 600,
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                >Đăng xuất + xoá cookie</button>
              </div>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
