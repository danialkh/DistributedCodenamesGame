import pytest

exit_code = pytest.main(['-v'])
print(f"Tests finished with exit code {exit_code}")
