"""The shell has to start without the optional 'llm' extra.

LLMCommand used to build its Azure OpenAI client at registration, so a core
install crashed before the prompt appeared. The client is now built the
first time `llm` runs, and only that command reports the missing extra.
"""
import cjtrade.apps.cjtrade_shell.cjtrade_shell as shell
import cjtrade.apps.cjtrade_shell.cjtrade_shell_legacy as legacy
import cjtrade.pkgs.llm.azure_openai as azure
import pytest


@pytest.fixture
def without_llm_extra(monkeypatch):
    # What azure_openai.py sees when `openai` is not installed.
    monkeypatch.setattr(azure, "AzureOpenAI", None)


@pytest.mark.parametrize("module", [shell, legacy], ids=["shell", "legacy"])
def test_the_shell_registers_its_commands_without_the_llm_extra(
        module, without_llm_extra):
    module.register_commands()
    assert "llm" in module.command_registry


@pytest.mark.parametrize("module", [shell, legacy], ids=["shell", "legacy"])
def test_using_llm_without_the_extra_names_the_extra(module, without_llm_extra):
    command = module.LLMCommand()
    with pytest.raises(ImportError, match=r"'llm' extra"):
        command.llm
