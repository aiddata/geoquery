angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory) {
  $scope.currentStep = $state;
  $scope.showCart = false;
  $scope.queryLen = 0;

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
