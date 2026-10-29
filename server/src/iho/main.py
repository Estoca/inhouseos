from iho.config import get_settings
from iho.server import create_application

app = create_application(get_settings())
