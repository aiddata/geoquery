angular.module('aiddataDET')
.controller('DetailsCtrl', function($scope, $rootScope, $log, $q, $timeout, $state, $element, $mdDialog, queryFactory, mapFactory, spinFactory) {
  $scope.queryObj = queryFactory.getQuery();
  $scope.queryData = {
    email: '',
    custom_name: 'Unamed Request'
  };

  var submitAlert = $mdDialog.confirm()
      .clickOutsideToClose(true)
      .title('Your Request Has been Submitted!')
      .ok('Review Request Status')
      .cancel('Start New Search');

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.submitQuery = function () {
    var id;

    spinFactory.start();

    queryFactory.submitRequest($scope.queryData)
      .then(function(data) {
        spinFactory.stop();
        id = data.request._id.$id;
        return $mdDialog.show(submitAlert);
      })
      .then(function() {
        return $state.go('status', { id: id });
      })
      .catch(function (err) {
        $log.error(err);
        return $state.go('map');
      })
      .finally(function() {
        /* This Reset Call is Not Working */
        queryFactory.resetQuery();
      });
  };

  $scope.$on('$viewContentLoaded', function() {
    mapFactory.provision(document.querySelector('.map'), true)
      .promise.then(function(){
        var sub = queryFactory.getSubBoundary().name;
        mapFactory.mapBoundary(sub);
      });

  });

});
