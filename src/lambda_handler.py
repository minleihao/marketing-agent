from mangum import Mangum

from webapp import app

handler = Mangum(app)
