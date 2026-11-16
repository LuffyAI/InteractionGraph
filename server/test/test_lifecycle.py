import unittest
from unittest.mock import patch

from dotvectordb.ConversationMemoryTree import ConversationMemoryTree
from knowledge_graph.CodexInteractionGraph import CodexInteractionGraph


class LifecycleTests(unittest.TestCase):
    def test_inherits_lifecycle_and_forwards_constructor_arguments(self):
        for name in ('__aenter__', '__aexit__'):
            self.assertIs(getattr(CodexInteractionGraph, name), getattr(ConversationMemoryTree, name))
            self.assertNotIn(name, CodexInteractionGraph.__dict__)
        with patch.object(ConversationMemoryTree, '__init__', return_value=None) as initialize:
            graph = CodexInteractionGraph('memory')
            initialize.assert_called_once_with('memory')
            self.assertEqual(graph.pending, {})
        self.assertNotIn('open', CodexInteractionGraph.__dict__)
        self.assertNotIn('close', CodexInteractionGraph.__dict__)
