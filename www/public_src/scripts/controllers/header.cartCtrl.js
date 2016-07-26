angular.module('aiddataDET')
.controller('CartCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory) {
  $scope.queryObj = {};
  $scope.query = '{}';

  $rootScope.$on('query:updated', function(event, data) {
    $scope.queryObj = data;
    $scope.query = JSON.stringify(data, null, 4);
  });

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.removeQuery = function (q, type) {
    queryFactory.removeRequest(q, type)
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
        // $scope.query = query;
      });
  };

});
