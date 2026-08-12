"""Compatibility facade for the TwinStudio 0.5 project-evolution engine.

The canonical implementation lives in :mod:`twinstudio.evolution`.  This module
keeps the early 0.5 import path working while avoiding a second divergent engine.
"""
from twinstudio.evolution import EvolutionResult, ProjectEvolutionEngine

EvolutionEngine = ProjectEvolutionEngine

__all__ = ["EvolutionEngine", "EvolutionResult", "ProjectEvolutionEngine"]
