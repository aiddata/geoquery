angular.module('aiddataDET')
.controller('DetailsCtrl', function($scope, $rootScope, $log, $q, $timeout, $state, $element, $mdDialog, queryFactory, modalFactory, mapFactory, spinFactory, info, modals) {
  $scope.queryObj = queryFactory.getQuery();
  $scope.terms = [];
  $scope.queryData = {
    email: '',
    custom_name: 'Request ' + d3.timeFormat('%m-%d-%y %H:%M')(Date.now())
  };

  var submitContent = _.extend(modals.submitted, info.submitted),
      submitAlert = modalFactory.confirm(submitContent);

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.submitQuery = function () {
    var id;

    spinFactory.start();

    queryFactory.submitRequest($scope.queryData)
      .then(function(data) {
        id = data.request._id.$id;
        $rootScope.$broadcast('query:updated');
        spinFactory.stop();
        return $mdDialog.show(submitAlert);
      })
      .then(function() {
        return $state.go('status', { id: id });
      })
      .catch(function (err) {
        $log.error(err);
        return $state.go('map', { confirmation: { confirmed: true }});
      })
      .finally(function() {
        spinFactory.stop();
      });
  };

  $scope.$on('$viewContentLoaded', function() {
    $scope.terms = _.get(info, 'terms_and_conditions.content') || [];
    $scope.citation = _.get(info, 'citation') || '';

    mapFactory.provision(document.querySelector('.map'), true)
      .promise.then(function(){
        var sub = queryFactory.getSubBoundary().name;
        mapFactory.mapBoundary(sub);
      });

  });

});
