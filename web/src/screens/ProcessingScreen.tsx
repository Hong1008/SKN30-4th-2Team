import { createClientId } from '../utils/clientId'
import { useEffect, useMemo, useRef, useState } from "react"

import { AlertCircle, Check, ChevronRight, RefreshCw } from "lucide-react"

import { api } from "../api/api"

import { getErrorMessage } from "../utils/apiErrors"

import type { ReviewData, ReviewProgress, ReviewSseEvent } from "../types"

import { useToast } from "../contexts/ToastContext"

import { useMetadata } from "../contexts/MetadataContext"

import { getMetadataLabel } from "../utils/metadata"

import {
  isTerminalReviewState,
  toReviewProgress,
} from "../utils/reviewProgress"

import { getNextAction } from "../utils/apiErrors"

interface Props {
  reviewId: string | null

  onDone: () => void

  onRetry: (reviewId: string) => void

  onStartNewReview: () => void
}

type Mode = "running" | "error" | "done"

const CONNECTION_WATCHDOG_MS = 10_000

export default function ProcessingScreen({
  reviewId,
  onDone,
  onRetry,
  onStartNewReview,
}: Props) {
  const { metadata } = useMetadata()

  const { showToast } = useToast()

  const stages = useMemo(
    () =>
      (metadata?.progress_stages ?? []).map((code) => ({
        code,

        label: getMetadataLabel(
          metadata?.progress_stage_details,
          code,
          "진행 단계",
        ),
      })),

    [metadata?.progress_stage_details, metadata?.progress_stages],
  )

  const [activeStep, setActiveStep] = useState(0)

  const [progress, setProgress] = useState<ReviewProgress | null>(null)

  const [mode, setMode] = useState<Mode>("running")

  const [errorMessage, setErrorMessage] = useState("")

  const [retryable, setRetryable] = useState(false)

  const [reviewState, setReviewState] = useState<"QUEUED" | "REVIEWING">(
    "QUEUED",
  )

  const retryRequestKey = useRef<string | null>(null)

  useEffect(() => {
    if (mode !== "running" || !reviewId) return

    let subscribed = true
    let source: EventSource | null = null
    let pollingTimer: ReturnType<typeof setTimeout> | null = null
    let pollingStarted = false
    let terminalReached = false
    let hasSseEvent = false
    let lastSequence = -1
    let lastServerActivityAt = Date.now()
    let watchdogTimer: ReturnType<typeof setTimeout> | null = null
    const initialController = new AbortController()
    const pollingController = new AbortController()

    const stopPolling = () => {
      pollingStarted = false
      if (pollingTimer) {
        clearTimeout(pollingTimer)
        pollingTimer = null
      }
    }

    const clearWatchdog = () => {
      if (watchdogTimer) {
        clearTimeout(watchdogTimer)
        watchdogTimer = null
      }
    }

    const noteServerActivity = () => {
      lastServerActivityAt = Date.now()
    }

    const finishStream = () => {
      terminalReached = true
      stopPolling()
      clearWatchdog()
      initialController.abort()
      pollingController.abort()
      source?.close()
    }

    const update = (
      nextState: string,
      nextProgress?: ReviewProgress | null,
      reviewError?: ReviewData["error"],
    ) => {
      if (!subscribed || terminalReached) return
      if (nextProgress && nextProgress.sequence > lastSequence) {
        lastSequence = nextProgress.sequence
        setProgress(nextProgress)
        const index = stages.findIndex(
          (stage) => stage.code === nextProgress.stage,
        )
        if (index >= 0) setActiveStep(index)
      }
      if (nextState === "QUEUED" || nextState === "REVIEWING")
        setReviewState(nextState)
      if (nextState === "COMPLETED") {
        finishStream()
        setActiveStep(Math.max(stages.length - 1, 0))
        setMode("done")
      } else if (["FAILED", "CANCELLED", "EXPIRED"].includes(nextState)) {
        finishStream()
        setMode("error")
        setErrorMessage(
          getErrorMessage(reviewError, "검토가 중단되었거나 만료되었습니다."),
        )
        setRetryable(
          reviewError?.retryable === true ||
            getNextAction(reviewError) === "RETRY_REVIEW",
        )
      }
    }

    const startPolling = () => {
      if (!subscribed || terminalReached || pollingStarted) return
      pollingStarted = true
      const poll = async () => {
        try {
          const response = await api.pollReviewStatus(
            reviewId,
            pollingController.signal,
          )
          if (!subscribed || terminalReached || !pollingStarted) return
          noteServerActivity()
          update(
            response.data.review_state,
            response.data.progress,
            response.data.error,
          )
          if (
            !terminalReached &&
            !isTerminalReviewState(response.data.review_state)
          ) {
            pollingTimer = setTimeout(poll, 2000)
          }
        } catch (error: any) {
          if (!subscribed || terminalReached || error?.name === "AbortError")
            return
          if (error?.status === 404 || error?.status === 410) {
            finishStream()
            showToast(
              "검토 정보를 찾을 수 없거나 만료되었습니다. 처음부터 다시 시작해 주세요.",
              "error",
            )
            setMode("error")
            setErrorMessage("검토 정보를 찾을 수 없거나 만료되었습니다.")
            setRetryable(false)
            return
          }
          setMode("error")
          setErrorMessage(
            getErrorMessage(error, "검토 상태를 불러오지 못했습니다."),
          )
          setRetryable(
            error?.retryable === true ||
              getNextAction(error) === "RETRY_REVIEW",
          )
        }
      }
      void poll()
    }

    void api
      .pollReviewStatus(reviewId, initialController.signal)
      .then((response) => {
        if (!subscribed || terminalReached || hasSseEvent) return
        noteServerActivity()
        update(
          response.data.review_state,
          response.data.progress,
          response.data.error,
        )
      })
      .catch((error: any) => {
        if (error?.name === "AbortError") return
        // 초기 REST 실패만으로 fallback polling을 시작하지 않는다. SSE 오류가 이를 결정한다.
      })

    try {
      source = new EventSource(api.reviewEventsUrl(reviewId), {
        withCredentials: true,
      })
      const onEvent = (event: MessageEvent<string>) => {
        if (terminalReached) return
        try {
          const data = JSON.parse(event.data) as ReviewSseEvent
          const sequence = Number.isFinite(data.sequence)
            ? data.sequence
            : Number(event.lastEventId)
          if (
            !Number.isFinite(sequence) ||
            (sequence <= lastSequence && !isTerminalReviewState(data.review_state))
          ) return
          if (!hasSseEvent) {
            hasSseEvent = true
            initialController.abort()
          }
          noteServerActivity()
          stopPolling()
          update(
            data.review_state,
            toReviewProgress({ ...data, sequence }),
            data.error,
          )
        } catch {
          source?.close()
          startPolling()
        }
      }
      source.addEventListener("progress", onEvent)
      source.addEventListener("completed", onEvent)
      source.addEventListener("failed", onEvent)
      source.onopen = () => {
        noteServerActivity()
        stopPolling()
      }
      source.onerror = () => startPolling()
    } catch {
      startPolling()
    }

    const monitorConnection = () => {
      if (!subscribed || terminalReached || pollingStarted) return
      if (Date.now() - lastServerActivityAt >= CONNECTION_WATCHDOG_MS) {
        startPolling()
        return
      }
      watchdogTimer = setTimeout(monitorConnection, 1_000)
    }
    watchdogTimer = setTimeout(monitorConnection, 1_000)

    return () => {
      subscribed = false
      stopPolling()
      clearWatchdog()
      initialController.abort()
      pollingController.abort()
      source?.close()
    }
  }, [mode, reviewId, showToast, stages])
  const retry = async () => {
    if (!reviewId) return

    try {
      const idempotencyKey = retryRequestKey.current ?? createClientId()

      retryRequestKey.current = idempotencyKey

      const response = await api.retryReview(reviewId, idempotencyKey)

      retryRequestKey.current = null

      setActiveStep(0)

      setProgress(null)
      setReviewState("QUEUED")
      setErrorMessage("")
      setRetryable(false)
      setMode("running")

      onRetry(response.data.review_id)
    } catch (error: any) {
      if (
        error?.code === "REVIEW_NOT_COMPLETED" ||
        error?.code === "REVIEW_ALREADY_RUNNING"
      ) {
        try {
          const latest = await api.pollReviewStatus(reviewId)
          if (
            latest.data.review_state === "QUEUED" ||
            latest.data.review_state === "REVIEWING"
          ) {
            setReviewState(latest.data.review_state)
            setProgress(latest.data.progress)
            setErrorMessage("")
            setRetryable(false)
            setMode("running")
            return
          }
        } catch {
          // 원래 재시도 오류를 사용자에게 안내한다.
        }
      }
      setErrorMessage(getErrorMessage(error, "재시도 요청에 실패했습니다."))

      setRetryable(
        error?.retryable === true || getNextAction(error) === "RETRY_REVIEW",
      )
    }
  }

  if (!reviewId)
    return <p className="text-sm text-rose-600">검토 ID를 찾을 수 없습니다.</p>

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-950">
          {reviewState === "QUEUED"
            ? "검토 요청이 접수되었습니다"
            : "계약서를 검토하고 있습니다"}
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          {reviewState === "QUEUED"
            ? "검토를 시작할 준비를 하고 있습니다."
            : "진행 상태는 실시간으로 갱신됩니다."}
        </p>
      </div>
      {mode !== "error" && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex justify-between text-sm">
            <span className="font-semibold text-slate-800">검토 진행 상태</span>
            <span className="font-semibold tabular-nums text-blue-700">
              {progress?.percent ?? 0}%
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full bg-blue-600 transition-all"
              style={{ width: `${progress?.percent ?? 0}%` }}
            />
          </div>
          {progress?.message && (
            <p className="mt-3 text-sm leading-6 text-slate-600">
              {progress.message}
            </p>
          )}
        </div>
      )}
      <section className="relative rounded-2xl border border-slate-200 bg-white px-5 py-3">
        <span
          aria-hidden="true"
          className="absolute bottom-9 left-[38px] top-9 w-px bg-slate-200"
        />
        {stages.map((stage, index) => {
          const complete = mode === "done" || index < activeStep

          const active = index === activeStep && mode === "running"

          return (
            <div
              key={stage.code}
              className={`relative flex items-center gap-4 rounded-xl px-1 py-3 transition-colors ${
                active ? "bg-blue-50/60 pr-4" : ""
              }`}
            >
              <span
                className={`relative z-10 grid size-7 shrink-0 place-items-center rounded-full bg-white ${
                  active ? "ring-4 ring-blue-100" : ""
                }`}
              >
                {complete ? (
                  <Check className="size-5 text-blue-600" />
                ) : active ? (
                  <RefreshCw className="size-5 animate-spin text-blue-600" />
                ) : (
                  <span className="size-3 rounded-full border border-slate-300 bg-white" />
                )}
              </span>
              <span
                className={`text-sm ${
                  active
                    ? "font-semibold text-blue-800"
                    : complete
                      ? "font-medium text-slate-600"
                      : "text-slate-400"
                }`}
              >
                {stage.label}
              </span>
            </div>
          )
        })}
      </section>
      {mode === "error" && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/40 p-5 text-sm leading-6 text-rose-700">
          <AlertCircle className="mr-2 inline size-4" />
          {errorMessage}
        </div>
      )}
      {mode === "error" && retryable && (
        <button
          onClick={retry}
          className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/20"
        >
          <RefreshCw className="size-4" />
          다시 시도
        </button>
      )}
      {mode === "error" && !retryable && (
        <button
          onClick={onStartNewReview}
          className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-slate-500/20"
        >
          새 검토 시작
        </button>
      )}
      {mode === "done" && (
        <button
          onClick={onDone}
          className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/20"
        >
          검토 결과 확인 <ChevronRight className="size-4" />
        </button>
      )}
    </div>
  )
}
