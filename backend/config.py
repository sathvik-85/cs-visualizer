from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    max_self_heal_attempts: int = 3
    manim_output_dir: str = "/tmp/manim_outputs"
    manim_timeout: int = 180  # seconds per render attempt
    use_layout_engine: bool = False  # layout engine adds overhead; use direct LLM code gen

    # Optional SMTP for email notifications (leave blank to disable)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    class Config:
        env_file = "../.env"
        extra = "ignore"


settings = Settings()
