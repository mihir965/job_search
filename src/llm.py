"""LLM integration for email personalization."""
import logging
from typing import Optional
from anthropic import Anthropic

from .config import config
from .utils import truncate_text

logger = logging.getLogger(__name__)


class LLMEmailGenerator:
    """Generates personalized cold emails using Claude."""

    def __init__(self):
        api_key = config.apis.get('anthropic_key')
        self.enabled = config.llm.get('enabled', True) and api_key
        if self.enabled:
            self.client = Anthropic(api_key=api_key)
            self.model = config.llm.get('model', 'claude-sonnet-4-20250514')
            self.max_tokens = config.llm.get('max_tokens', 500)
        else:
            logger.warning("LLM email generation disabled - no API key or disabled in config")

    def generate_email(self, hm_name: str, hm_title: str, company: str,
                      role_title: str, role_url: str,
                      role_description: Optional[str] = None) -> Optional[str]:
        """Generate a personalized cold email for a specific role."""
        if not self.enabled:
            logger.debug("LLM disabled, returning None")
            return None

        # Truncate role description if too long
        if role_description:
            role_description = truncate_text(role_description, max_words=300)

        # Get relevant highlights from profile
        highlights = config.profile.get('highlights', [])
        highlights_text = '\n'.join(f"- {h}" for h in highlights[:4])  # Top 4

        # Build prompt
        user_prompt = f"""Write a cold email from Mihir to {hm_name} ({hm_title}) at {company} about this role:

Role: {role_title}
Role URL: {role_url}
{f'Role Description: {role_description}' if role_description else ''}

Mihir's relevant highlights:
{highlights_text}

Output ONLY the email body — no subject line, no "Subject:", no commentary."""

        system_prompt = """You are helping Mihir Kulkarni write a brief, professional cold email to a hiring manager about a specific job opening.

About Mihir:
- MS CS student at Rutgers, graduating May 2026
- Focused on systems programming in C/C++
- Key projects:
  * Real-time counseling platform (multi-user TCP server in C with epoll, stateful room management, LLM backend integration, rebuilding in C++)
  * Preemptive threading library with MLFQ and CFS schedulers from scratch
  * FPGA research with Prof. Richard Martin
- Production experience: Full-time engineer at Syngenta (data pipelines, AWS), intern at UniteGPS (full-stack SaaS)
- Targeting systems/infrastructure/quant developer roles
- Requires H-1B sponsorship (do NOT mention this in the email)

Rules:
- Keep the email under 150 words
- Be genuine and specific — mention 1-2 things about the role that connect to Mihir's experience
- Do NOT be overly formal or use corporate buzzwords
- Do NOT mention visa/sponsorship
- Do NOT use phrases like "I am writing to express my interest" or "I believe I would be a great fit"
- End with a soft ask: "Would you have 15 minutes to chat this week?"
- Include github.com/mihir965 at the bottom
- The tone should sound like a confident peer reaching out, not a desperate applicant
- Match the most relevant 1-2 highlights from Mihir's experience to the specific role requirements"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            email_body = response.content[0].text
            logger.info(f"Generated personalized email for {role_title} at {company}")
            return email_body

        except Exception as e:
            logger.error(f"LLM email generation failed: {e}")
            return None


# Global instance
llm_generator = LLMEmailGenerator()
