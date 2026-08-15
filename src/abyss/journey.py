"""Composition façade for the seeded ABYSS golden path."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from .adapters import ActionReceipt, SandboxAdapters
from .agents import KnowledgeAgent, MatchingAgent, OnboardingAgent
from .booking import (
    BookingAgent,
    BookingPreferences,
    BookingSlot,
    SandboxBookingService,
)
from .catalogs import SeededCatalog
from .care_paths import (
    AlternativePlanScenario,
    CarePathSelection,
    HospitalCareOption,
    build_alternative_scenario,
    build_hospital_options,
)
from .domain import CareState, ConsentAction, DecisionFact, VerificationStatus
from .evaluation import PathEvaluation, evaluate, rank
from .knowledge import (
    HospitalKnowledgeCatalog,
    NoHospitalKnowledgeCatalog,
    PublishedHospitalRate,
)
from .memory import FactLedger
from .observability import AuditLedger, JourneyEvent
from .procedures import ProcedureCatalog, ProcedureResolution
from .workflow import AbyssWorkflow, WorkflowStage


@dataclass(slots=True)
class CareJourney:
    journey_id: str
    workflow: AbyssWorkflow
    catalogs: SeededCatalog = field(default_factory=SeededCatalog)
    adapters: SandboxAdapters = field(default_factory=SandboxAdapters)
    matching_agent: MatchingAgent = field(default_factory=MatchingAgent)
    onboarding_agent: OnboardingAgent = field(default_factory=OnboardingAgent)
    knowledge_agent: KnowledgeAgent = field(default_factory=KnowledgeAgent)
    evaluations: list[PathEvaluation] = field(default_factory=list)
    receipts: list[ActionReceipt] = field(default_factory=list)
    onboarding_missing: tuple[str, ...] = ()
    onboarding_questions: tuple[str, ...] = ()
    procedure_catalog: ProcedureCatalog = field(default_factory=ProcedureCatalog)
    procedure_resolution: ProcedureResolution | None = None
    matching_reason: str | None = None
    hospital_knowledge: HospitalKnowledgeCatalog = field(default_factory=NoHospitalKnowledgeCatalog)
    hospital_rates: list[PublishedHospitalRate] = field(default_factory=list)
    current_plan_id: str = "continuation"
    current_plan_options: list[HospitalCareOption] = field(default_factory=list)
    alternative_plan: AlternativePlanScenario | None = None
    selected_care_path: CarePathSelection | None = None
    booking_agent: BookingAgent = field(default_factory=BookingAgent)
    booking_service: SandboxBookingService = field(default_factory=SandboxBookingService)
    booking_preferences: BookingPreferences | None = None
    booking_slots: list[BookingSlot] = field(default_factory=list)
    selected_booking_slot: BookingSlot | None = None
    reschedule_original_slot: BookingSlot | None = None
    reschedule_pending: bool = False
    memory: FactLedger = field(default_factory=FactLedger)
    audit: AuditLedger = field(default_factory=AuditLedger)

    @classmethod
    def open(cls, journey_id: str, user_id: str = "synthetic-user", **agents: object) -> "CareJourney":
        """Open a journey; agent dependencies may be injected for tests."""
        return cls(journey_id, AbyssWorkflow(CareState(session_id=f"{journey_id}:{user_id}")), **agents)

    @property
    def stage(self) -> WorkflowStage:
        return self.workflow.stage

    def record_fact(self, fact: DecisionFact) -> None:
        self.workflow.care_state.add_fact(fact)
        self.memory.append(self.workflow.care_state.session_id, f"fact-{len(self.memory.records(self.workflow.care_state.session_id)) + 1}", fact)
        self.audit.append(self.journey_id, "fact_recorded", actor="journey", payload={"name": fact.name, "status": fact.verification_status.value})

    def onboard(self, text: str, *, source: str):
        """Run bounded intake extraction and store candidate facts.

        The agent may propose facts; the ledger preserves their inferred state.
        No journey stage or decision is advanced by model output alone.
        """
        if self.stage != WorkflowStage.INTAKE:
            raise RuntimeError("onboarding is only available in intake stage")
        existing_facts = {
            name: {"value": fact.value, "verification_status": fact.verification_status.value}
            for name, fact in self.workflow.care_state.facts.items()
        }
        proposal = self.onboarding_agent.extract(
            text,
            source=source,
            context={
                "existing_facts": existing_facts,
                "pending_fields": list(self.onboarding_missing),
                "pending_questions": list(self.onboarding_questions),
            },
        )
        existing_procedure = self.workflow.care_state.facts.get("requested_procedure")
        procedure_phrase = str(existing_procedure.value) if existing_procedure else ""
        for fact in proposal.facts:
            if fact.name == "requested_procedure" and existing_procedure is not None:
                # Preserve explicit information across turns. The model proposes
                # the merge; the source-backed catalog validates it before the
                # fact ledger replaces the previous procedure value.
                procedure_phrase = (
                    f"{existing_procedure.value} {fact.value} {text.strip()}"
                )
                merged_resolution = self.knowledge_agent.propose_procedure(
                    procedure_phrase
                )
                merged_value = (
                    merged_resolution.canonical_name
                    if not merged_resolution.needs_confirmation
                    else f"{existing_procedure.value}; {fact.value}"
                )
                fact = replace(fact, value=merged_value)
            elif fact.name == "requested_procedure":
                procedure_phrase = f"{fact.value} {text.strip()}"
            self.record_fact(fact)
        procedure_fact = self.workflow.care_state.facts.get("requested_procedure")
        procedure = procedure_fact.value if procedure_fact else None
        if procedure:
            normalized = " ".join(text.lower().replace("-", " ").split())
            existing_code = self.workflow.care_state.facts.get("procedure_code")
            confirmed_code = str(existing_code.value) if existing_code else None
            if "without contrast" in normalized or "no contrast" in normalized:
                confirmed_code = "73721"
            elif "with contrast" in normalized:
                confirmed_code = "73722"
            if not procedure_phrase:
                procedure_phrase = str(procedure)
            self.procedure_resolution = self.knowledge_agent.propose_procedure(
                procedure_phrase, confirmed_code=confirmed_code
            )
            if not self.procedure_resolution.needs_confirmation:
                self.record_fact(DecisionFact("procedure_code", self.procedure_resolution.code,
                                               "procedure_catalog", procedure_fact.observed_at,
                                               1.0, VerificationStatus.VERIFIED))
        required = {
            "requested_procedure": "What care or procedure are you trying to arrange?",
            "service_date": "What date do you expect to receive this care?",
            "coverage_end_date": "When does your current coverage end?",
        }
        missing = [name for name in required if name not in self.workflow.care_state.facts]
        questions = [required[name] for name in missing]
        if self.procedure_resolution is not None and self.procedure_resolution.needs_confirmation:
            missing.append("procedure_code_confirmation")
            if self.procedure_resolution.candidates:
                candidate_names = self.procedure_catalog.names_for(
                    self.procedure_resolution.candidates
                )
                choices = " or ".join(candidate_names)
                questions.append(
                    f"Should this be {choices}?" if choices
                    else "Which specific procedure did your clinician order?"
                )
            else:
                questions.append(
                    "What body area and specific type of procedure did your clinician order? "
                    "I need those details to find the matching catalog entry."
                )
        self.onboarding_missing = tuple(missing)
        self.onboarding_questions = tuple(questions)
        self.audit.append(self.journey_id, "onboarding_completed", actor="onboarding_agent",
                          payload={"source": source, "fact_count": len(proposal.facts)})
        return proposal

    def record_consent(self, action: ConsentAction, *, approved: bool, scope: str, actor: str = "synthetic-user") -> None:
        self.workflow.care_state.record_consent(action, approved=approved, scope=scope, actor=actor)
        self.audit.append(self.journey_id, "consent_recorded", actor=actor, payload={"action": action.value, "approved": approved, "scope": scope})

    def compare(self, plan_ids: list[str], provider_id: str = "dr-lee") -> list[PathEvaluation]:
        if self.stage != WorkflowStage.COMPARE:
            raise RuntimeError("comparison is only available in compare stage")
        request = self.matching_agent.request_evaluation(plan_ids, provider_id=provider_id)
        provider = self.catalogs.provider(request.provider_id)
        procedure_code = self.workflow.care_state.facts.get("procedure_code")
        self.hospital_rates = (
            self.hospital_knowledge.prices_for_code(str(procedure_code.value))
            if procedure_code else []
        )
        self.audit.append(
            self.journey_id,
            "hospital_catalog_retrieved",
            actor="knowledge_engine",
            payload={
                "procedure_code": str(procedure_code.value) if procedure_code else None,
                "source": self.hospital_knowledge.source_name,
                "facility_count": len(self.hospital_rates),
                "network_status": "unknown",
            },
        )
        self.evaluations = rank([evaluate(self.catalogs.plan(plan_id), provider) for plan_id in request.plan_ids])
        current_plan = self.catalogs.plan(self.current_plan_id)
        self.current_plan_options = build_hospital_options(
            current_plan,
            self.hospital_rates,
            coverage_status="current",
        )
        feasible_alternatives = [
            item for item in self.evaluations
            if item.feasible and item.plan_id != self.current_plan_id
        ]
        self.alternative_plan = None
        if self.current_plan_options and feasible_alternatives:
            alternative = self.catalogs.plan(feasible_alternatives[0].plan_id)
            self.alternative_plan = build_alternative_scenario(
                alternative,
                self.hospital_rates,
                self.current_plan_options[0].estimated_annual_total,
            )
        self.audit.append(self.journey_id, "matching_requested", actor="matching_agent",
                          payload={"plan_ids": list(request.plan_ids), "provider_id": request.provider_id})
        self.audit.append(self.journey_id, "evaluation_completed", actor="engine",
                          payload={"evaluation_count": len(self.evaluations),
                                   "feasible_count": sum(item.feasible for item in self.evaluations)})
        return self.evaluations

    def select_current_care_path(self, hospital_id: int) -> CarePathSelection:
        if self.stage != WorkflowStage.RECOMMEND:
            raise RuntimeError("a care path can only be selected from recommendation")
        option = next(
            (item for item in self.current_plan_options if item.hospital_id == hospital_id),
            None,
        )
        if option is None:
            raise RuntimeError("hospital is not an available current-plan option")
        self.selected_care_path = CarePathSelection.from_option(option)
        self.audit.append(
            self.journey_id,
            "care_path_selected",
            actor="user",
            payload={
                "plan_id": option.plan_id,
                "coverage_status": option.coverage_status,
                "hospital_id": option.hospital_id,
                "hospital": option.hospital,
                "network_status": option.network_status,
            },
        )
        next_stage = self.workflow.continue_current_coverage()
        self.audit.append(
            self.journey_id,
            "stage_advanced",
            actor="engine",
            payload={"stage": next_stage.value, "path": "keep_current_coverage"},
        )
        return self.selected_care_path

    def collect_booking_preferences(self, text: str) -> list[BookingSlot]:
        if self.stage != WorkflowStage.BOOK:
            raise RuntimeError("booking preferences are only accepted in booking stage")
        if not self.selected_care_path:
            raise RuntimeError("select a care path before searching appointment slots")
        if self.selected_care_path.network_status != "sandbox_verified":
            raise RuntimeError("network and provider verification is required before slot search")
        service_date = self.workflow.care_state.facts.get("service_date")
        default_date = str(service_date.value) if service_date else "2026-08-30"
        try:
            datetime.fromisoformat(default_date)
        except ValueError:
            default_date = "2026-08-30"
        self.booking_preferences = self.booking_agent.collect_preferences(
            text,
            default_date=default_date,
        )
        self.selected_booking_slot = None
        self.booking_slots = self.booking_service.search_slots(
            hospital_id=self.selected_care_path.hospital_id,
            hospital=self.selected_care_path.hospital,
            procedure_code=self.selected_care_path.procedure_code,
            preferences=self.booking_preferences,
        )
        self.audit.append(
            self.journey_id,
            "booking_slots_retrieved",
            actor="booking_agent",
            payload={
                "slot_count": len(self.booking_slots),
                "hospital_id": self.selected_care_path.hospital_id,
                "procedure_code": self.selected_care_path.procedure_code,
            },
        )
        return self.booking_slots

    def select_booking_slot(self, slot_id: str) -> BookingSlot:
        if self.stage != WorkflowStage.BOOK and not (
            self.stage == WorkflowStage.COMPLETE and self.reschedule_original_slot
        ):
            raise RuntimeError("appointment slots can only be selected in booking stage")
        slot = next((item for item in self.booking_slots if item.slot_id == slot_id), None)
        if slot is None or slot.status != "available":
            raise RuntimeError("appointment slot is not available for this journey")
        if not self.selected_care_path:
            raise RuntimeError("select a care path before choosing an appointment slot")
        if (
            slot.hospital_id != self.selected_care_path.hospital_id
            or slot.procedure_code != self.selected_care_path.procedure_code
        ):
            raise RuntimeError("appointment slot does not match the selected care path")
        self.selected_booking_slot = slot
        self.audit.append(
            self.journey_id,
            "booking_slot_selected",
            actor="user",
            payload={"slot_id": slot.slot_id, "starts_at": slot.starts_at},
        )
        return slot

    def begin_reschedule(self, text: str) -> list[BookingSlot]:
        """Search replacements while preserving the confirmed appointment."""
        if self.stage != WorkflowStage.COMPLETE or not self.selected_booking_slot:
            raise RuntimeError("a confirmed appointment is required before rescheduling")
        confirmed = self.booking_service.slot(self.selected_booking_slot.slot_id)
        if confirmed is None or confirmed.status != "booked":
            raise RuntimeError("the original appointment is not confirmed")
        self.reschedule_original_slot = confirmed
        self.reschedule_pending = False
        service_date = self.workflow.care_state.facts.get("service_date")
        default_date = str(service_date.value) if service_date else "2026-08-30"
        self.booking_preferences = self.booking_agent.collect_preferences(
            text, default_date=default_date,
        )
        self.selected_booking_slot = None
        self.booking_slots = [
            slot for slot in self.booking_service.search_slots(
                hospital_id=self.selected_care_path.hospital_id,
                hospital=self.selected_care_path.hospital,
                procedure_code=self.selected_care_path.procedure_code,
                preferences=self.booking_preferences,
            ) if slot.slot_id != confirmed.slot_id
        ]
        self.audit.append(
            self.journey_id,
            "reschedule_slots_retrieved",
            actor="care_journey_agent",
            payload={"original_slot_id": confirmed.slot_id, "slot_count": len(self.booking_slots)},
        )
        return self.booking_slots

    @property
    def cancellation_consent_scope(self) -> str | None:
        slot = self.reschedule_original_slot
        if not slot:
            return None
        return f"cancel {slot.slot_id} / {slot.hospital} / {slot.starts_at}"

    def execute_reschedule(
        self,
        *,
        booking_scope: str,
        cancellation_scope: str,
        idempotency_key: str,
    ) -> tuple[ActionReceipt, ActionReceipt | None]:
        """Confirm the replacement before cancelling the original appointment."""
        if self.stage != WorkflowStage.COMPLETE or not self.reschedule_original_slot:
            raise RuntimeError("rescheduling is not active")
        if not self.selected_booking_slot:
            raise RuntimeError("choose a replacement appointment first")
        if booking_scope != self.booking_consent_scope:
            raise RuntimeError("replacement booking consent scope does not match")
        if cancellation_scope != self.cancellation_consent_scope:
            raise RuntimeError("cancellation consent scope does not match")
        if not self.workflow.care_state.has_consent(ConsentAction.BOOK_APPOINTMENT, booking_scope):
            raise RuntimeError("replacement booking approval is required")
        if not self.workflow.care_state.has_consent(ConsentAction.CANCEL_APPOINTMENT, cancellation_scope):
            raise RuntimeError("original appointment cancellation approval is required")
        attempt = self.booking_service.request_booking(
            journey_id=self.journey_id,
            slot_id=self.selected_booking_slot.slot_id,
            expected_scope=self.booking_consent_scope,
            consent_scope=booking_scope,
            idempotency_key=idempotency_key,
        )
        replacement = ActionReceipt(
            ConsentAction.BOOK_APPOINTMENT.value,
            "scheduled_retry" if attempt.status == "scheduled_retry" else "sandbox_confirmed",
            self.journey_id, booking_scope, idempotency_key, datetime.now(UTC),
        )
        self.receipts.append(replacement)
        if attempt.status == "scheduled_retry":
            self.reschedule_pending = True
            return replacement, None
        cancellation = self._complete_reschedule(cancellation_scope, idempotency_key)
        return replacement, cancellation

    def _complete_reschedule(self, cancellation_scope: str, idempotency_key: str) -> ActionReceipt:
        original = self.reschedule_original_slot
        if original is None:
            raise RuntimeError("original appointment is unavailable")
        self.booking_service.cancel_booking(original.slot_id)
        cancellation = ActionReceipt(
            ConsentAction.CANCEL_APPOINTMENT.value, "sandbox_confirmed",
            self.journey_id, cancellation_scope, f"{idempotency_key}-cancel",
            datetime.now(UTC),
        )
        self.receipts.append(cancellation)
        self.reschedule_original_slot = None
        self.reschedule_pending = False
        self.audit.append(
            self.journey_id, "appointment_rescheduled", actor="booking_agent",
            payload={"cancelled_slot_id": original.slot_id,
                     "replacement_slot_id": self.selected_booking_slot.slot_id},
        )
        return cancellation

    @property
    def booking_consent_scope(self) -> str | None:
        if not self.selected_booking_slot or not self.selected_care_path:
            return None
        return self.selected_booking_slot.consent_scope(self.selected_care_path.plan_name)

    def process_booking_tasks(self) -> None:
        completed = self.booking_service.process_due_tasks()
        for task in completed:
            if task.journey_id != self.journey_id:
                continue
            self.audit.append(
                self.journey_id,
                "booking_retry_completed" if task.status == "completed" else "booking_retry_blocked",
                actor="booking_task_worker",
                payload={
                    "task_id": task.task_id,
                    "status": task.status,
                    "attempts": task.attempts,
                },
            )
            if task.status != "completed":
                continue
            replacement = ActionReceipt(
                ConsentAction.BOOK_APPOINTMENT.value,
                "sandbox_confirmed",
                self.journey_id,
                task.consent_scope,
                task.idempotency_key,
                datetime.now(UTC),
            )
            self.receipts = [
                replacement if item.idempotency_key == task.idempotency_key else item
                for item in self.receipts
            ]
            if self.selected_care_path:
                self.selected_care_path = replace(
                    self.selected_care_path,
                    booking_consent=True,
                )
            if self.reschedule_pending:
                cancellation_scope = self.cancellation_consent_scope
                if cancellation_scope is None:
                    raise RuntimeError("reschedule cancellation scope is unavailable")
                self._complete_reschedule(cancellation_scope, task.idempotency_key)
            if self.stage == WorkflowStage.BOOK:
                self.workflow.advance()

    def explain_matching(self, question: str = "Why did these care paths pass or fail?") -> str:
        """Optional model explanation; never required for deterministic comparison."""
        if not self.evaluations:
            raise RuntimeError("comparison must run before matching explanation")
        self.matching_reason = self.matching_agent.reason_about_evaluation(
            self.evaluations,
            question=question,
            care_path_context={
                "current_plan": self.catalogs.plan(self.current_plan_id).name,
                "current_plan_options": [item.as_dict() for item in self.current_plan_options],
                "alternative_plan": (
                    self.alternative_plan.as_dict() if self.alternative_plan else None
                ),
                "limitations": [
                    "published rate is not confirmed plan allowed amount",
                    "network status pending verification",
                    "alternative requires separate eligibility and switching flow",
                ],
            },
        )
        self.audit.append(self.journey_id, "matching_explanation_completed", actor="matching_agent",
                          payload={"model_backed": True, "evaluation_count": len(self.evaluations)})
        return self.matching_reason

    def advance(self) -> WorkflowStage:
        next_stage = self.workflow.advance()
        self.audit.append(self.journey_id, "stage_advanced", actor="engine", payload={"stage": next_stage.value})
        return next_stage

    def execute(self, action: ConsentAction, scope: str, idempotency_key: str) -> ActionReceipt:
        if not self.workflow.care_state.has_consent(action, scope):
            raise RuntimeError(f"{action.value} approval is required")
        expected_stage = {
            ConsentAction.ENROLL_PLAN: WorkflowStage.ENROLL,
            ConsentAction.TRANSITION_COVERAGE: WorkflowStage.TRANSITION,
            ConsentAction.SHARE_WITH_PROVIDER: WorkflowStage.VERIFY,
            ConsentAction.BOOK_APPOINTMENT: WorkflowStage.BOOK,
        }.get(action)
        if expected_stage is not None and self.stage != expected_stage:
            raise RuntimeError(f"{action.value} is not allowed in {self.stage.value} stage")
        if action == ConsentAction.TRANSITION_COVERAGE:
            required = {"new_effective_date", "first_premium_confirmed"}
            missing = sorted(required - self.workflow.care_state.facts.keys())
            if missing:
                raise RuntimeError(f"coverage transition prerequisites missing: {', '.join(missing)}")
        if action == ConsentAction.BOOK_APPOINTMENT and self.selected_booking_slot:
            expected_scope = self.booking_consent_scope
            if expected_scope is None:
                raise RuntimeError("booking consent scope is unavailable")
            attempt = self.booking_service.request_booking(
                journey_id=self.journey_id,
                slot_id=self.selected_booking_slot.slot_id,
                expected_scope=expected_scope,
                consent_scope=scope,
                idempotency_key=idempotency_key,
            )
            receipt = ActionReceipt(
                action.value,
                "scheduled_retry" if attempt.status == "scheduled_retry" else "sandbox_confirmed",
                self.journey_id,
                scope,
                idempotency_key,
                datetime.now(UTC),
            )
            if attempt.task:
                self.audit.append(
                    self.journey_id,
                    "booking_retry_scheduled",
                    actor="booking_agent",
                    payload={
                        "task_id": attempt.task.task_id,
                        "slot_id": attempt.task.slot_id,
                        "next_attempt_at": attempt.task.next_attempt_at,
                    },
                )
        else:
            receipt = self.adapters.execute(action.value, self.journey_id, scope, idempotency_key)
        if not any(item.idempotency_key == idempotency_key for item in self.receipts):
            self.receipts.append(receipt)
        if self.selected_care_path and action == ConsentAction.SHARE_WITH_PROVIDER:
            self.selected_care_path = replace(
                self.selected_care_path,
                network_status="sandbox_verified",
            )
        if self.selected_care_path and action == ConsentAction.BOOK_APPOINTMENT:
            self.selected_care_path = replace(
                self.selected_care_path,
                booking_consent=True,
            )
        self.audit.append(self.journey_id, "sandbox_receipt", actor="adapter", payload={"action": action.value, "status": receipt.status, "idempotency_key": idempotency_key})
        return receipt
