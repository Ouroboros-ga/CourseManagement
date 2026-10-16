/** 请求关联发起时的账号/学院，且仅最后一次请求可回写。 */
export function identityContext(user: { id: string } | null): string {
  return typeof user?.id === 'string' ? user.id : ''
}

export class ContextEpoch {
  private revision = 0
  constructor(private readonly contextKey: () => string) {}
  begin() {
    const revision = ++this.revision
    const key = this.contextKey()
    return {
      isCurrent: () => revision === this.revision && key === this.contextKey(),
      isLatest: () => revision === this.revision
    }
  }
  invalidate() { this.revision++ }
}
