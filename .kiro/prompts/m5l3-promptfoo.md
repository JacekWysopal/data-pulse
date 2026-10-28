# Wprowadzenie promptfoo do projektu — v2

## Badanie

/10x-research code-review-evals Przeanalizuj obecny stan '<reviewer-dir>' w kontekście potencjalnego wprowadzenia ewaluacji — możliwość ponownego wykorzystania promptów, importowalność agenta itd. Moim pierwszym wyborem narzędzia do ewaluacji jest promptfoo. Jeśli mój stos technologiczny jest zgodny z tym narzędziem, idź w tym kierunku. W przeciwnym razie możesz przeanalizować inne narzędzia oss, które umożliwiają mi ewaluację moich promptów i agentów. Użyj Web Search lub context7, aby uzyskać najnowszą dokumentację.

## Plan

/10x-plan code-review-evals Zaplanuj, jak wprowadzić promptfoo w '<reviewer-dir>', zaczynając od `m5l3-promptfooconfig.yaml.template`. Moim celem jest utworzenie pierwszej konfiguracji, która testuje ten sam prompt do przeglądu kodu na trzech różnych modelach (z-ai/glm-5.3, deepseek/deepseek-v4.1-flash i openai/gpt-5.6-luna) przez OpenRouter. Dla przypadków testowych powinien istnieć jeden, dość złożony diff migrujący komponent React 16 do React 19+ z trzema istotnymi błędami. LLM-as-a-judge powinien weryfikować, czy wyniki przeglądu kodu poprawnie identyfikują, co jest zepsute. Dodaj również statyczną asercję javascript sprawdzającą, czy werdykt przeglądu to \"fail\".