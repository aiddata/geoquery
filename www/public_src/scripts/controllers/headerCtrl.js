angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory) {
  $scope.currentStep = $state;
  $scope.queryLen = 0;

  $scope.tabs = {
    options:  {
      cart: { active: false, text: 'View Cart', icon: 'fa-shopping-cart' },
      help: { active: false, text: 'Help', icon: 'fa-question-circle' },
      previousRequests: { active: false, text: 'View Past Requests', icon: 'fa-history' }
    },
    order: ['cart', 'previousRequests', 'help']
  };

  $scope.activate = function (tab) {
    _.each($scope.tabs, function(t) { t.active = false; });
    tab.active = true;
  };

  $rootScope.$on('query:updated', function(event, data) {
    $scope.queryLen = querySize(data);
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    $scope.currentStep = toState;
  });

  function querySize (query) {
    return _.chain(query.raster_data)
      .map(function(d) {
        var fileSize = _.size(_.get(d, 'files')),
            extractSize = _.size(_.get(d, 'options.extract_types'));

        return fileSize * extractSize;
      })
      .sum()
      .add(_.size(_.get(query, 'release_data')))
      .value();
  }

});
