from common import *
from sklearn.ensemble import HistGradientBoostingClassifier,HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.compose import TransformedTargetRegressor
CFG=dict(max_iter=100,max_leaf_nodes=7,min_samples_leaf=60,learning_rate=.05,l2_regularization=10.,early_stopping=False,random_state=20261109)
class Hurdle:
 def __init__(self,indices):self.indices=np.asarray(indices)
 def fit(self,X,y):
  x=X[:,self.indices];active=abs(y)>1;self.p=HistGradientBoostingClassifier(**CFG).fit(x,active);self.v=HistGradientBoostingRegressor(**CFG).fit(x[active],y[active]);self.n_active=int(active.sum());return self
 def predict(self,X):
  x=X[:,self.indices];return self.p.predict_proba(x)[:,1]*self.v.predict(x)
 def predict_activity(self,X):return self.p.predict_proba(X[:,self.indices])[:,1]
def linear():return make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler(),Ridge(alpha=10.))
def neural():return TransformedTargetRegressor(regressor=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler(),MLPRegressor(hidden_layer_sizes=(64,32),alpha=10.,max_iter=150,early_stopping=False,random_state=20261109)),transformer=StandardScaler())

class EventHead:
 def __init__(self,method,indices):self.method=method;self.indices=indices
 def score(self,X):
  if self.method.startswith('EMA72'):return X[:,self.indices[0]]*self.sign
  if self.method.startswith('latest_or_age'):return X[:,self.indices[0]]*self.sign
  p=np.clip(self.estimator.predict_proba(X[:,self.indices])[:,1],1e-6,1-1e-6);return np.log(p/(1-p))
 def predict(self,X):return self.calibrator.predict_proba(self.score(X).reshape(-1,1))[:,1]

