import json
import re
import anthropic
import google.generativeai as genai
from groq import AsyncGroq
from prompts import SYSTEM_PROMPT, build_repair_prompt
from scene_graph.json_prompt import SYSTEM_PROMPT_JSON, build_json_repair_prompt
from scene_graph.schema import SceneGraph


def extract_code(raw: str) -> str:
    """Strip markdown fences and normalize class names."""
    raw = re.sub(r"```(?:python)?\s*\n?", "", raw)
    raw = raw.replace("```", "").strip()
    raw = re.sub(r"class\s+\w+\s*\(\s*VoiceoverScene\s*\)\s*:",
                 "class GeneratedScene(VoiceoverScene):", raw)
    raw = re.sub(r"class\s+\w+\s*\(\s*MovingCameraScene\s*\)\s*:",
                 "class GeneratedScene(MovingCameraScene):", raw)
    raw = re.sub(r"class\s+\w+\s*\(\s*Scene\s*\)\s*:",
                 "class GeneratedScene(Scene):", raw)
    return raw


def _strip_json_fences(raw: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences the LLM might add."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)
    return raw.strip()


def _validate_scene_graph_references(scene: SceneGraph) -> None:
    """Verify all element ids referenced in steps exist in the elements dict."""
    element_ids = set(scene.elements.keys())
    for step in scene.steps:
        for eid in step.introduce_elements:
            if eid not in element_ids:
                raise ValueError(
                    f"Step {step.step_id}: introduce_elements references unknown id '{eid}'"
                )
        for eid in step.remove_elements:
            if eid not in element_ids:
                raise ValueError(
                    f"Step {step.step_id}: remove_elements references unknown id '{eid}'"
                )
        for action in step.actions:
            tid = getattr(action, "target_id", None)
            if tid and tid not in element_ids:
                raise ValueError(
                    f"Step {step.step_id}: action.target_id '{tid}' not in elements dict"
                )


# ── Provider call helpers ──────────────────────────────────────────────────────

async def _call_anthropic(
    model: str, api_key: str, user_prompt: str, temperature: float,
    system_override: str | None = None,
) -> str:
    client = anthropic.AsyncAnthropic(api_key=api_key)
    system = system_override if system_override is not None else SYSTEM_PROMPT
    response = await client.messages.create(
        model=model,
        max_tokens=8192,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


async def _call_gemini(
    model: str, api_key: str, user_prompt: str, temperature: float,
    system_override: str | None = None,
) -> str:
    genai.configure(api_key=api_key)
    system = system_override if system_override is not None else SYSTEM_PROMPT
    gmodel = genai.GenerativeModel(
        model_name=model,
        system_instruction=system,
        generation_config=genai.GenerationConfig(temperature=temperature),
    )
    response = await gmodel.generate_content_async(user_prompt)
    return response.text


async def _call_groq(
    model: str, api_key: str, user_prompt: str, temperature: float,
    system_override: str | None = None,
) -> str:
    client = AsyncGroq(api_key=api_key)
    system = system_override if system_override is not None else SYSTEM_PROMPT
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=8192,
    )
    return resp.choices[0].message.content


PROVIDER_DISPATCH = {
    "Anthropic": _call_anthropic,
    "Google":    _call_gemini,
    "Groq":      _call_groq,
}


async def _call(
    provider: str, model: str, api_key: str, user_prompt: str,
    temperature: float, system_override: str | None = None,
) -> str:
    fn = PROVIDER_DISPATCH.get(provider)
    if fn is None:
        raise ValueError(f"Unknown provider: {provider}")
    if not api_key:
        raise ValueError(f"No API key provided. Please enter your {provider} key in the UI.")
    return await fn(model, api_key, user_prompt, temperature, system_override)


# ── Code-gen path (original) ───────────────────────────────────────────────────

async def generate_manim_code(topic: str, provider: str, model: str, api_key: str, sse_queue=None) -> str:
    raw = await _call(
        provider, model, api_key,
        f"Create a Manim animation with voiceover for: {topic}",
        temperature=0.4,
    )
    return extract_code(raw)


async def repair_manim_code(topic: str, broken_code: str, error_output: str, attempt: int,
                             provider: str, model: str, api_key: str, sse_queue=None) -> str:
    raw = await _call(
        provider, model, api_key,
        build_repair_prompt(topic, broken_code, error_output, attempt),
        temperature=0.2,
    )
    return extract_code(raw)


# ── Scene graph path (new) ─────────────────────────────────────────────────────

async def generate_scene_graph(
    topic: str, provider: str, model: str, api_key: str,
    max_repair_attempts: int = 3,
) -> SceneGraph:
    """Call LLM to produce a SceneGraph JSON, with up to max_repair_attempts fixes."""
    user_prompt = f"Create a scene graph for: {topic}"
    raw = await _call(
        provider, model, api_key, user_prompt,
        temperature=0.3, system_override=SYSTEM_PROMPT_JSON,
    )

    last_error = ""
    for attempt in range(max_repair_attempts):
        try:
            cleaned = _strip_json_fences(raw)
            data = json.loads(cleaned)
            scene = SceneGraph.model_validate(data)
            _validate_scene_graph_references(scene)
            return scene
        except Exception as e:
            last_error = str(e)
            if attempt < max_repair_attempts - 1:
                raw = await _call(
                    provider, model, api_key,
                    build_json_repair_prompt(topic, raw, last_error),
                    temperature=0.1, system_override=SYSTEM_PROMPT_JSON,
                )

    raise RuntimeError(
        f"Scene graph generation failed after {max_repair_attempts} attempts. "
        f"Last error: {last_error}"
    )
