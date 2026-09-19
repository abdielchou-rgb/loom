"""Keel —— 叙事编译器 (Narrative Compiler).

Idea -> Narrative IR -> Renderers

IR 采用三层正交结构（Riedl & Young, IPOCL, JAIR 2010）：
    L1 因果情节层  plot causality
    L2 角色目标层  character intention
    L3 作者意图层  authorial commitment
"""

from .ir.models import (
    NarrativeIR,
    PlotLayer,
    CharacterLayer,
    CommitmentLayer,
    EventNode,
    CausalLink,
    Character,
    GoalNode,
    ActantBinding,
    Commitment,
    SceneNode,
    Enigma,
    StoryBible,
    Entity,
    Relation,
)
from .ir.enums import (
    ActantRole,
    EnigmaState,
    Focalization,
    Frequency,
    SceneOutcome,
    Severity,
)
from .ir.templates import BeatTemplate, BeatSpec, get_template, list_templates
from .validators import run_all, Report, Finding
from .audit.anti_slop import scan_slop
from .provenance.meter import ProvenanceLedger
from .render import render_text, render_fountain, render_storyboard
from .llm import (
    Generator,
    MockGenerator,
    LiteLLMGenerator,
    Prompt,
    TokenLedger,
    build_generator,
)
from .pipeline import KeelPipeline, PipelineResult
from .audience import AudienceSimulator, AudienceReport, Persona

__version__ = "1.0.0"

__all__ = [
    "NarrativeIR",
    "PlotLayer",
    "CharacterLayer",
    "CommitmentLayer",
    "EventNode",
    "CausalLink",
    "Character",
    "GoalNode",
    "ActantBinding",
    "Commitment",
    "SceneNode",
    "Enigma",
    "StoryBible",
    "Entity",
    "Relation",
    "ActantRole",
    "EnigmaState",
    "Focalization",
    "Frequency",
    "SceneOutcome",
    "Severity",
    "BeatTemplate",
    "BeatSpec",
    "get_template",
    "list_templates",
    "run_all",
    "Report",
    "Finding",
    "scan_slop",
    "ProvenanceLedger",
    "render_text",
    "render_fountain",
    "render_storyboard",
    "Generator",
    "MockGenerator",
    "LiteLLMGenerator",
    "Prompt",
    "TokenLedger",
    "build_generator",
    "KeelPipeline",
    "PipelineResult",
    "AudienceSimulator",
    "AudienceReport",
    "Persona",
]
