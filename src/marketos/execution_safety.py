"""The single provenance-bound paper/shadow execution boundary for C13-1."""
from __future__ import annotations

from .authoritative_books import (
    AuthoritativePortfolioBook,
    C13RiskGate,
    DurableLedger,
    reconcile_book,
)
from .errors import DuplicateConflict, ExecutionStateChanged, InvariantViolation
from .canonical import canonical_sha256
from .orders import ExecutionMode, OrderIntent, OrderState
from .paper import ExecutionReport, PaperBroker, PendingExecution, PreparedExecution
from .risk import RiskAction
from .time import ClockQuality


class C13PreTradeEnvelope:
    """Derive, gate, and atomically commit one non-live paper/shadow intent."""

    def __init__(
        self,
        *,
        broker: PaperBroker,
        book: AuthoritativePortfolioBook,
        ledger: DurableLedger,
    ) -> None:
        if not isinstance(broker, PaperBroker):
            raise InvariantViolation("INVALID_PAPER_BROKER")
        if not isinstance(book, AuthoritativePortfolioBook):
            raise InvariantViolation("AUTHORITATIVE_BOOK_REQUIRED")
        if not isinstance(ledger, DurableLedger):
            raise InvariantViolation("DURABLE_LEDGER_REQUIRED")
        if broker.portfolio is not book:
            raise InvariantViolation("BROKER_BOOK_IDENTITY_MISMATCH")
        if book.ledger is not ledger:
            raise InvariantViolation("BOOK_LEDGER_IDENTITY_MISMATCH")
        self.broker = broker
        self.book = book
        self.ledger = ledger
        self._capability = object()
        self._transaction_owner = object()
        broker._bind_envelope_capability(self._capability)
        ledger._bind_execution_owner(self._transaction_owner)

    def _cached(self, intent: OrderIntent) -> ExecutionReport | None:
        existing = self.broker._reports.get(intent.idempotency_key)
        if existing is None:
            return None
        existing_hash, report = existing
        intent_hash = intent.sha256()
        if existing_hash != intent_hash:
            raise DuplicateConflict(
                f"IDEMPOTENCY_KEY_CONFLICT:{intent.idempotency_key}"
            )
        uncached = report.__class__(
            intent_id=report.intent_id,
            state=report.state,
            risk_decision=report.risk_decision,
            fills=report.fills,
            remaining_quantity=report.remaining_quantity,
            reasons=report.reasons,
            inserted=False,
            c13_gate_sha256=report.c13_gate_sha256,
            portfolio_snapshot_sha256=report.portfolio_snapshot_sha256,
            ledger_head_sha256=report.ledger_head_sha256,
            market_view_sha256=report.market_view_sha256,
            report_sha256="",
            live_trading_state=report.live_trading_state,
        )
        return report.__class__(
            intent_id=uncached.intent_id,
            state=uncached.state,
            risk_decision=uncached.risk_decision,
            fills=uncached.fills,
            remaining_quantity=uncached.remaining_quantity,
            reasons=uncached.reasons,
            inserted=False,
            c13_gate_sha256=uncached.c13_gate_sha256,
            portfolio_snapshot_sha256=uncached.portfolio_snapshot_sha256,
            ledger_head_sha256=uncached.ledger_head_sha256,
            market_view_sha256=uncached.market_view_sha256,
            report_sha256=canonical_sha256(uncached.canonical_dict(include_hash=False)),
            live_trading_state=uncached.live_trading_state,
        )

    @staticmethod
    def _pending_without_mutation(
        prepared: PreparedExecution,
        report: ExecutionReport,
    ) -> PendingExecution:
        return PendingExecution(
            intent=prepared.intent,
            intent_sha256=prepared.intent_sha256,
            report=report,
            updated_market=None,
        )

    @staticmethod
    def _gate_reasons(gate, prepared: PreparedExecution, reconciliation) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *gate.reasons,
                    *prepared.decision.reasons,
                    *reconciliation.reasons,
                )
            )
        )

    @staticmethod
    def _veto_gate(gate, reason: str):
        return C13RiskGate._build_decision(
            action=RiskAction.NO_TRADE,
            intent_id=gate.intent_id,
            reasons=tuple(dict.fromkeys((*gate.reasons, reason))),
            upstream_decision_sha256=gate.upstream_decision_sha256,
            reconciliation_sha256=gate.reconciliation_sha256,
            portfolio_snapshot_sha256=gate.portfolio_snapshot_sha256,
            ledger_head_sha256=gate.ledger_head_sha256,
            market_view_sha256=gate.market_view_sha256,
        )

    def _report_for_gate(
        self,
        prepared: PreparedExecution,
        gate,
        reconciliation,
        *,
        state: OrderState = OrderState.REJECTED,
        reasons: tuple[str, ...] | None = None,
    ) -> ExecutionReport:
        return self.broker._report(
            intent=prepared.intent,
            state=state,
            decision=prepared.decision,
            fills=(),
            remaining=prepared.intent.quantity,
            reasons=(
                self._gate_reasons(gate, prepared, reconciliation)
                if reasons is None
                else reasons
            ),
            inserted=True,
            c13_gate_sha256=gate.sha256(),
            portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
            ledger_head_sha256=prepared.ledger_head_sha256,
            market_view_sha256=prepared.market_view_sha256,
        )

    def _finalize_report_at_head(
        self,
        prepared: PreparedExecution,
        report: ExecutionReport,
    ) -> tuple[bool, str | None]:
        try:
            with self.ledger.execution_transaction(
                prepared.ledger_head_sha256,
                owner=self._transaction_owner,
            ):
                pass
        except ExecutionStateChanged:
            return False, "EXECUTION_STATE_CHANGED"
        except InvariantViolation as exc:
            if str(exc) in {"JOURNAL_INTEGRITY_FAILURE", "BOOK_SOURCE_TAINTED"}:
                return False, None
            raise
        self.broker._finalize_pending(
            self._pending_without_mutation(prepared, report),
            capability=self._capability,
        )
        return True, None

    def submit(
        self,
        intent: OrderIntent,
        *,
        now_ns: int,
        clock_quality: ClockQuality,
    ) -> ExecutionReport:
        if not isinstance(intent, OrderIntent):
            raise InvariantViolation("INVALID_ORDER_INTENT")
        with self.broker._lock:
            cached = self._cached(intent)
            if cached is not None:
                return cached

            prepared = self.broker._prepare(
                intent,
                now_ns=now_ns,
                clock_quality=clock_quality,
            )
            current_snapshot = self.book.snapshot()
            if current_snapshot != prepared.portfolio_snapshot:
                raise ExecutionStateChanged("EXECUTION_PORTFOLIO_CHANGED")
            reconciliation = reconcile_book(self.ledger, prepared.portfolio_snapshot)
            gate = C13RiskGate().evaluate(
                prepared.decision,
                reconciliation,
                intent.mode,
                portfolio_snapshot_sha256=prepared.portfolio_snapshot_sha256,
                ledger_head_sha256=prepared.ledger_head_sha256,
                market_view_sha256=prepared.market_view_sha256,
            )

            if gate.action is RiskAction.NO_TRADE:
                report = self._report_for_gate(prepared, gate, reconciliation)
                finalized, reason = self._finalize_report_at_head(prepared, report)
                if finalized:
                    return self.broker._reports[intent.idempotency_key][1]
                if reason is not None:
                    race_gate = self._veto_gate(gate, reason)
                    return self._report_for_gate(
                        prepared,
                        race_gate,
                        reconciliation,
                        reasons=tuple(dict.fromkeys((*report.reasons, reason))),
                    )
                return report

            if intent.mode is ExecutionMode.SHADOW:
                report = self._report_for_gate(
                    prepared,
                    gate,
                    reconciliation,
                    state=OrderState.CANCELLED,
                    reasons=("SHADOW_MODE_NO_EXECUTION",),
                )
                finalized, reason = self._finalize_report_at_head(prepared, report)
                if finalized:
                    return self.broker._reports[intent.idempotency_key][1]
                if reason is not None:
                    race_gate = self._veto_gate(gate, reason)
                    return self._report_for_gate(
                        prepared,
                        race_gate,
                        reconciliation,
                        reasons=tuple(dict.fromkeys((*report.reasons, reason))),
                    )
                return report

            try:
                with self.ledger.execution_transaction(
                    prepared.ledger_head_sha256,
                    owner=self._transaction_owner,
                ):
                    pending = self.broker._commit_authorized(
                        prepared,
                        capability=self._capability,
                        transaction_owner=self._transaction_owner,
                        c13_gate=gate,
                    )
                    if pending.report.fills:
                        self.ledger.checkpoint(
                            f"c13-1:{intent.idempotency_key}",
                            self.book,
                            captured_at_ns=now_ns,
                        )
                return self.broker._finalize_pending(
                    pending,
                    capability=self._capability,
                )
            except ExecutionStateChanged as exc:
                race_gate = self._veto_gate(gate, str(exc))
                return self._report_for_gate(
                    prepared,
                    race_gate,
                    reconciliation,
                    reasons=tuple(dict.fromkeys((*gate.reasons, str(exc)))),
                )
