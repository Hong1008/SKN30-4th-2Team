import { act, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import ProcessingScreen from "./ProcessingScreen"
import { api } from "../api/api"

vi.mock("../api/api", () => ({
  api: {
    pollReviewStatus: vi.fn(),
    reviewEventsUrl: vi.fn(() => "/events"),
    retryReview: vi.fn(),
  },
}))
const metadata = {
  progress_stages: ["PREPARING", "ANALYZING"],
  progress_stage_details: [
    { code: "PREPARING", label: "준비" },
    { code: "ANALYZING", label: "분석" },
  ],
}

vi.mock("../contexts/MetadataContext", () => ({
  useMetadata: () => ({ metadata }),
}))
const showToast = vi.fn()

vi.mock("../contexts/ToastContext", () => ({ useToast: () => ({ showToast }) }))

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  listeners = new Map<string, (event: MessageEvent<string>) => void>()
  close = vi.fn()

  constructor() {
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    this.listeners.set(type, listener as (event: MessageEvent<string>) => void)
  }
  emit(type: string, data: Record<string, unknown>, lastEventId = "") {
    this.listeners.get(type)?.({
      data: JSON.stringify(data),
      lastEventId,
    } as MessageEvent<string>)
  }
}

const props = {
  reviewId: "review-1",
  onDone: vi.fn(),
  onRetry: vi.fn(),
  onStartNewReview: vi.fn(),
}
const response = (
  sequence: number,
  percent: number,
  review_state = "REVIEWING",
) => ({
  data: {
    review_id: "review-1",
    review_state,
    progress: { sequence, stage: "ANALYZING", percent, message: `${percent}%` },
    error: null,
  },
})

beforeEach(() => {
  vi.clearAllMocks()
  FakeEventSource.instances = []
  vi.stubGlobal("EventSource", FakeEventSource)
})

afterEach(() => vi.useRealTimers())

describe("검토 진행 SSE", () => {
  it("정상 SSE 연결 중에는 watchdog 폴링을 시작하지 않는다", async () => {
    vi.useFakeTimers()
    vi.mocked(api.pollReviewStatus).mockResolvedValue(response(0, 0) as never)
    render(<ProcessingScreen {...props} />)
    await act(async () => {
      await Promise.resolve()
    })
    act(() => {
      FakeEventSource.instances[0].onopen?.()
    })
    await act(async () => {
      vi.advanceTimersByTime(20_000)
      await Promise.resolve()
    })
    expect(api.pollReviewStatus).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it("확인된 SSE 오류가 발생할 때만 fallback 폴링을 하나 시작한다", async () => {
    vi.mocked(api.pollReviewStatus).mockReturnValue(new Promise(() => {}))
    render(<ProcessingScreen {...props} />)
    const source = FakeEventSource.instances[0]
    act(() => {
      source.onerror?.()
      source.onerror?.()
    })
    expect(api.pollReviewStatus).toHaveBeenCalledTimes(2)
  })

  it("같거나 이전 sequence 이벤트는 버려 진행률이 역행하지 않는다", async () => {
    vi.mocked(api.pollReviewStatus).mockReturnValue(new Promise(() => {}))
    render(<ProcessingScreen {...props} />)
    const source = FakeEventSource.instances[0]
    act(() => {
      source.emit("progress", {
        sequence: 2,
        review_state: "REVIEWING",
        stage: "ANALYZING",
        percent: 70,
        message: "70%",
      })
      source.emit("progress", {
        sequence: 2,
        review_state: "REVIEWING",
        stage: "PREPARING",
        percent: 20,
        message: "20%",
      })
      source.emit("progress", {
        sequence: 1,
        review_state: "REVIEWING",
        stage: "PREPARING",
        percent: 10,
        message: "10%",
      })
    })
    expect(screen.getAllByText("70%")).toHaveLength(2)
    expect(screen.queryByText("20%")).not.toBeInTheDocument()
  })

  it("terminal 이벤트 이후의 nonterminal 이벤트를 무시하고 연결을 닫는다", async () => {
    vi.mocked(api.pollReviewStatus).mockReturnValue(new Promise(() => {}))
    render(<ProcessingScreen {...props} />)
    const source = FakeEventSource.instances[0]
    act(() => {
      source.emit("completed", {
        sequence: 3,
        review_state: "COMPLETED",
        stage: "ANALYZING",
        percent: 100,
        message: "완료",
      })
      source.emit("progress", {
        sequence: 4,
        review_state: "REVIEWING",
        stage: "ANALYZING",
        percent: 50,
        message: "되돌아감",
      })
    })
    expect(
      await screen.findByRole("button", { name: /검토 결과 확인/ }),
    ).toBeInTheDocument()
    expect(screen.queryByText("되돌아감")).not.toBeInTheDocument()
    expect(source.close).toHaveBeenCalled()
  })

  it("SSE 이벤트가 먼저 오면 늦은 초기 REST 응답으로 덮어쓰지 않는다", async () => {
    let resolveInitial: (value: any) => void
    vi.mocked(api.pollReviewStatus).mockReturnValue(
      new Promise((resolve) => {
        resolveInitial = resolve
      }),
    )
    render(<ProcessingScreen {...props} />)
    act(() =>
      FakeEventSource.instances[0].emit("progress", {
        sequence: 2,
        review_state: "REVIEWING",
        stage: "ANALYZING",
        percent: 80,
        message: "80%",
      }),
    )
    await act(async () => {
      resolveInitial(response(1, 30))
      await Promise.resolve()
    })
    expect(screen.getAllByText("80%")).toHaveLength(2)
    expect(screen.queryByText("30%")).not.toBeInTheDocument()
  })
  it("SSE onopen 후 진행 중 fallback 응답을 무효화한다", async () => {
    let resolveFallback: (value: any) => void
    vi.mocked(api.pollReviewStatus)
      .mockReturnValueOnce(new Promise(() => {}))
      .mockReturnValueOnce(new Promise(resolve => { resolveFallback = resolve }))
    render(<ProcessingScreen {...props} />)
    const source = FakeEventSource.instances[0]

    act(() => source.onerror?.())
    act(() => source.onopen?.())
    await act(async () => {
      resolveFallback(response(5, 90))
      await Promise.resolve()
    })

    expect(screen.queryByText("90%")).not.toBeInTheDocument()
  })

  it("컴포넌트 이탈 시 EventSource와 모든 REST 요청을 정리한다", () => {
    const signals: AbortSignal[] = []
    vi.mocked(api.pollReviewStatus).mockImplementation((_id, signal) => {
      if (signal) signals.push(signal)
      return new Promise(() => {})
    })
    const { unmount } = render(<ProcessingScreen {...props} />)
    const source = FakeEventSource.instances[0]
    act(() => source.onerror?.())

    unmount()

    expect(source.close).toHaveBeenCalled()
    expect(signals).toHaveLength(2)
    expect(signals.every(signal => signal.aborted)).toBe(true)
  })
  it("EventSource 자동 재연결 후 fallback을 멈추고 새 SSE 이벤트를 반영한다", async () => {
    vi.mocked(api.pollReviewStatus).mockReturnValue(new Promise(() => {}))
    render(<ProcessingScreen {...props} />)
    const source = FakeEventSource.instances[0]

    act(() => source.onerror?.())
    expect(source.close).not.toHaveBeenCalled()
    expect(api.pollReviewStatus).toHaveBeenCalledTimes(2)

    act(() => {
      source.onopen?.()
      source.emit("progress", {
        sequence: 3,
        review_state: "REVIEWING",
        stage: "ANALYZING",
        percent: 60,
        message: "재연결 완료",
      })
    })

    expect(await screen.findByText("재연결 완료")).toBeInTheDocument()
    expect(api.pollReviewStatus).toHaveBeenCalledTimes(2)
  })

  it("reviewId 변경 후 이전 review의 이벤트와 REST 응답을 폐기한다", async () => {
    let resolveOldRest: (value: any) => void
    vi.mocked(api.pollReviewStatus)
      .mockReturnValueOnce(new Promise(resolve => { resolveOldRest = resolve }))
      .mockReturnValueOnce(new Promise(() => {}))
    const { rerender } = render(<ProcessingScreen {...props} />)
    const oldSource = FakeEventSource.instances[0]

    rerender(<ProcessingScreen {...props} reviewId="review-2" />)
    const newSource = FakeEventSource.instances[1]
    expect(oldSource.close).toHaveBeenCalled()

    act(() => oldSource.emit("progress", {
      sequence: 9,
      review_state: "REVIEWING",
      stage: "ANALYZING",
      percent: 90,
      message: "이전 검토",
    }))
    await act(async () => {
      resolveOldRest(response(8, 80))
      await Promise.resolve()
    })
    act(() => newSource.emit("progress", {
      sequence: 1,
      review_state: "REVIEWING",
      stage: "PREPARING",
      percent: 10,
      message: "새 검토",
    }))

    expect(screen.queryByText("이전 검토")).not.toBeInTheDocument()
    expect(screen.queryByText("80%")).not.toBeInTheDocument()
    expect(await screen.findByText("새 검토")).toBeInTheDocument()
  })

  it.each(["FAILED", "CANCELLED", "EXPIRED"])(
    "%s terminal 상태에서 EventSource와 실행 중인 REST를 즉시 정리한다",
    async terminalState => {
      const signals: AbortSignal[] = []
      vi.mocked(api.pollReviewStatus).mockImplementation((_id, signal) => {
        if (signal) signals.push(signal)
        return new Promise(() => {})
      })
      render(<ProcessingScreen {...props} />)
      const source = FakeEventSource.instances[0]
      act(() => source.onerror?.())

      act(() => source.emit("failed", {
        sequence: 4,
        review_state: terminalState,
        stage: "ANALYZING",
        percent: 40,
        message: "중단",
        error: { code: "REVIEW_STOPPED", retryable: false },
      }))

      expect(await screen.findByRole("button", { name: "새 검토 시작" })).toBeInTheDocument()
      expect(source.close).toHaveBeenCalled()
      expect(signals).toHaveLength(2)
      expect(signals.every(signal => signal.aborted)).toBe(true)
    },
  )
})
