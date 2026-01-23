from app.core.config import settings

print(f"Type of ALLOWED_MODELS: {type(settings.ALLOWED_MODELS)}")
print(f"Content: {settings.ALLOWED_MODELS}")

assert isinstance(settings.ALLOWED_MODELS, set), "ALLOWED_MODELS should be a set"
assert "gemini-2.5-pro" in settings.ALLOWED_MODELS, "Model gemini-2.5-pro should be in the set"
print("✅ Optimization verified!")
