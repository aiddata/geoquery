angular.module('aiddataDET')
.controller('SelectionsCtrl', function($scope, $rootScope, $log, $stateParams, $state, $mdDialog, queryFactory) {
  $scope.queryObj = queryFactory.getQuery();

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.removeQuery = function (q, type) {
    if ($scope.queryObj.raster_data.length + $scope.queryObj.release_data.length === 1) {
      return $mdDialog.show(emptyRequest)
        .then(function() { deleteRequest(q, type); })
        .then($scope.addRequest);
    }
    deleteRequest(q, type);
  };

  $scope.addRequest = function () {
    $state.go('search', {
      boundary: queryFactory.getBoundary().boundaryId,
      subboundary: queryFactory.getSubBoundary().name
    });
  };

  var emptyRequest = $mdDialog.confirm()
      .clickOutsideToClose(true)
      .title('Are you sure you want to remove this selection?')
      .textContent('Your cart will be empty')
      .ok('Return to search')
      .cancel('Cancel');

  function deleteRequest (q, type) {
    return queryFactory.removeRequest(q, type)
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  }

});
