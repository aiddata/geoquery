angular.module('aiddataDET')
.controller('RequestsCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory) {
  $scope.queryObj = queryFactory.getQuery();

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.removeQuery = function (q, type) {
    queryFactory.removeRequest(q, type)
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  };

  $scope.addRequest = function () {
    $state.go('search', {
      boundary: queryFactory.getBoundary().boundaryId,
      subboundary: queryFactory.getSubBoundary().name
    });
  };

});
