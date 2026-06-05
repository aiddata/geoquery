angular.module('aiddataDET')
.controller('CartCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory, ajaxFactory) {
  $scope.queryObj = {};

  $rootScope.$on('query:updated', function(event, data) {
    $scope.queryObj = queryFactory.getQuery();
  });

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };


  $scope.goBack = function () {
    if (_.get(queryFactory.getBoundary(), 'boundaryId')) {
      $state.go('search', {
        boundary: _.get(queryFactory.getBoundary(), 'boundaryId'),
        subboundary: _.get(queryFactory.getSubBoundary(), 'name')
      });
    } else {
      $state.go('map');
    }
  };

  $scope.removeQuery = function (q, type) {
    queryFactory.removeRequest(q, type)
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  };

  $scope.submitQuery = function () {
    $state.go('checkout');
  };

});
