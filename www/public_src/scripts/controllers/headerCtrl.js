angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory) {
  $scope.currentStep = $state;
  $scope.query = '{}';
  $scope.queryLen = 0;

  $rootScope.$on('query:updated', function(event, data) {
    $scope.queryObj = data;
    $scope.queryLen = querySize(data);
    $scope.query = JSON.stringify(data, null, 4);
  });

  $scope.datasetDetails = queryFactory.getDataset;

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    $scope.currentStep = toState;
  });

  $rootScope.$on('$stateChangeError', function(event, toState, toParams, fromState, fromParams, error){
    $log.error(event, toState, toParams, fromState, fromParams, error);
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
