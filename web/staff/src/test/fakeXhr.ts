// A stand-in for XMLHttpRequest (Story 1.8 upload tests): records what was sent and
// lets a test report progress and answer, fail or time out each request.

type Listener = (event: ProgressEvent) => void;

class Events {
  private listeners = new Map<string, Listener[]>();

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  emit(type: string, event: Partial<ProgressEvent> = {}): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event as ProgressEvent);
    }
  }
}

export class FakeXhr extends Events {
  static requests: FakeXhr[] = [];

  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown = undefined;
  timeout = 0;
  status = 0;
  responseText = "";
  responseHeaders: Record<string, string> = {};
  aborted = false;
  readonly upload = new Events();

  constructor() {
    super();
    FakeXhr.requests.push(this);
  }

  static reset(): void {
    FakeXhr.requests = [];
  }

  static last(): FakeXhr {
    const request = FakeXhr.requests.at(-1);
    if (!request) throw new Error("no request was made");
    return request;
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  getResponseHeader(name: string): string | null {
    return this.responseHeaders[name] ?? null;
  }

  send(body: unknown): void {
    this.body = body;
  }

  abort(): void {
    this.aborted = true;
    this.emit("abort");
  }

  progress(loaded: number, total: number): void {
    this.upload.emit("progress", { lengthComputable: true, loaded, total });
  }

  respond(
    status: number,
    body: unknown,
    headers: Record<string, string> = {},
  ): void {
    this.status = status;
    this.responseText = typeof body === "string" ? body : JSON.stringify(body);
    this.responseHeaders = headers;
    this.emit("load");
  }

  fail(): void {
    this.emit("error");
  }

  timeOut(): void {
    this.emit("timeout");
  }
}
