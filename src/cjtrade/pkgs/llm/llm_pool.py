from cjtrade.pkgs.llm._llm_base import LLMClientBase
from cjtrade.pkgs.logger import get_logger

log = get_logger("llm")
# User's LLM pool (a set of available LLMs for fallback plan)

class LLMPool(LLMClientBase):
    """A list of LLM clients that fails over to the next one on error.

    Parameters
    ----------
    llms : list of LLMClientBase
        Clients to try, in order.
    """
    def __init__(self, llms: list[LLMClientBase]):
        self.llms = llms
        self.current_index = 0

    def get_current_llm(self):
        """Return the client currently in use.

        Raises
        ------
        Exception
            If the pool is empty.
        """
        if not self.llms:
            raise Exception("No LLMs available in the pool.")
        return self.llms[self.current_index]

    def get_next_llm(self):
        """Return the client after the current one, without switching to it.

        Raises
        ------
        Exception
            If the pool is empty.
        """
        if not self.llms:
            raise Exception("No LLMs available in the pool.")
        next_index = (self.current_index + 1) % len(self.llms)
        return self.llms[next_index]

    def generate_response(self, prompt):
        """Return a reply from the current client, failing over on errors.

        On an exception the pool logs the error, moves to the next client
        (wrapping around) and retries until some client returns a reply.

        Parameters
        ----------
        prompt : str
            The full prompt.

        Returns
        -------
        str
            The first successful reply.

        Warnings
        --------
        The member clients may call remote APIs (network, usage costs).
        If every client keeps failing, this loops forever.
        """
        current_llm = self.get_current_llm()
        response = None
        while response is None:
            try:
                response = current_llm.generate_response(prompt)
            except Exception as e:
                log.warning("LLM %s err: %s, falling back to next", current_llm, e)
                self._fallback()
                current_llm = self.get_current_llm()
        log.info("resp by LLM %s", current_llm)
        return response

    def _fallback(self):
        if not self.llms:
            raise Exception("No LLMs available in the pool.")
        self.current_index = (self.current_index + 1) % len(self.llms)
